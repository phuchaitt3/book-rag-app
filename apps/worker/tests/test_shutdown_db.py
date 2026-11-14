"""A worker told to stop mid-job leaves the job runnable (#228, ADR 0004).

These need Docker (testcontainers Postgres). No signal is sent: the stop event is what the
SIGTERM handler sets, so the tests behave the same on Windows.
"""

import asyncio
import uuid
from collections.abc import Sequence
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from test_ingestion import database_url as _database_url  # noqa: F401
from test_ingestion import make_pdf

from book_rag_api.jobs import enqueue_ingestion
from book_rag_api.models import EMBEDDING_DIM, Book, IngestionJob
from book_rag_worker.__main__ import init_schema, run
from book_rag_worker.config import WorkerSettings
from book_rag_worker.worker import Worker, build_worker


class BlockingEmbedder:
    """Signals that embedding started, then takes `seconds` per batch."""

    dimension = EMBEDDING_DIM

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self.started = asyncio.Event()

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.started.set()
        await asyncio.sleep(self.seconds)
        return [[0.0] * EMBEDDING_DIM for _ in texts]


@pytest.fixture
def url(_database_url: str) -> str:  # noqa: F811
    return _database_url


async def start_job(
    url: str, tmp_path: Path, embedder: BlockingEmbedder, grace: float
) -> tuple[Worker, uuid.UUID]:
    (tmp_path / "book.pdf").write_bytes(make_pdf())
    settings = WorkerSettings(
        database_url=url,
        storage_dir=tmp_path,
        embed_batch_size=4,
        shutdown_timeout=grace,
    )
    worker = build_worker(settings, embedder=embedder)  # type: ignore[arg-type]
    await init_schema(worker)
    async with AsyncSession(worker.engine) as session:
        book = Book(title="Sách thử", storage_key="book.pdf")
        session.add(book)
        await session.flush()
        book_id = book.id
        await session.commit()
    async with worker.app.open_async():
        job_id = await enqueue_ingestion(worker.engine, worker.app, book_id)
    return worker, job_id


async def read_state(url: str, job_id: uuid.UUID) -> tuple[str, str | None, str]:
    """(ingestion job status, its error, the queue's status for the same job)."""
    engine: AsyncEngine = create_async_engine(url)
    try:
        async with AsyncSession(engine) as session:
            job = await session.get(IngestionJob, job_id)
            assert job is not None
            queue_status = (
                await session.execute(
                    text("SELECT status FROM procrastinate_jobs WHERE args->>'job_id' = :id"),
                    {"id": str(job_id)},
                )
            ).scalar_one()
            return job.status, job.error, str(queue_status)
    finally:
        await engine.dispose()


async def stop_after_embedding_starts(
    worker: Worker, embedder: BlockingEmbedder
) -> asyncio.Task[None]:
    stop = asyncio.Event()
    task = asyncio.create_task(run(worker, stop))
    async with asyncio.timeout(60):
        await embedder.started.wait()
    stop.set()
    return task


async def test_stop_mid_job_returns_the_job_to_the_queue(url: str, tmp_path: Path) -> None:
    embedder = BlockingEmbedder(seconds=120)  # never finishes inside the grace period
    worker, job_id = await start_job(url, tmp_path, embedder, grace=0.5)
    task = await stop_after_embedding_starts(worker, embedder)
    await asyncio.wait_for(task, 60)  # exits cleanly: no exception

    status, error, queue_status = await read_state(url, job_id)
    assert status == "queued"  # runnable, not left "running" for the sweep to fail
    assert error is not None and "shutdown" in error
    assert queue_status == "todo"  # the queue will hand it to the next worker


async def test_stop_lets_a_job_that_finishes_in_time_complete(
    url: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO")
    embedder = BlockingEmbedder(seconds=0.3)
    worker, job_id = await start_job(url, tmp_path, embedder, grace=30)
    task = await stop_after_embedding_starts(worker, embedder)
    await asyncio.wait_for(task, 60)

    status, error, queue_status = await read_state(url, job_id)
    logs = " | ".join(f"{r.name}: {r.getMessage()}" for r in caplog.records)
    assert (status, queue_status) == ("succeeded", "succeeded"), (error, logs)


async def test_the_interrupted_job_runs_again_and_succeeds(url: str, tmp_path: Path) -> None:
    embedder = BlockingEmbedder(seconds=120)
    worker, job_id = await start_job(url, tmp_path, embedder, grace=0.5)
    task = await stop_after_embedding_starts(worker, embedder)
    await asyncio.wait_for(task, 60)

    # A fresh worker (the replacement process) picks the same job up and finishes it.
    fast = BlockingEmbedder(seconds=0)
    settings = WorkerSettings(database_url=url, storage_dir=tmp_path, embed_batch_size=4)
    second = build_worker(settings, embedder=fast)  # type: ignore[arg-type]
    async with second.app.open_async():
        await second.app.run_worker_async(wait=False, install_signal_handlers=False)
    await second.engine.dispose()

    status, _, queue_status = await read_state(url, job_id)
    assert (status, queue_status) == ("succeeded", "succeeded")
