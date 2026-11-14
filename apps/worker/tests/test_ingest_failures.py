"""Failure modes of ingestion (ADR 0004, issue 229): a killed worker, transient and permanent
embedder errors, and two workers racing for one job. Each test is a row of
docs/operations/failure-modes.md.
"""

import asyncio
import contextlib
import math
import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from book_rag.providers import FakeEmbedder
from book_rag_api.auth import DEV_OWNER, DEV_USER_HEADER
from book_rag_api.config import Settings
from book_rag_api.jobs import enqueue_ingestion
from book_rag_api.main import create_app
from book_rag_api.models import EMBEDDING_DIM, Book, Chunk, IngestionJob
from book_rag_worker.__main__ import init_schema
from book_rag_worker.config import WorkerSettings
from book_rag_worker.ingest import MAX_RETRIES, fail_stuck_jobs, run_ingestion
from book_rag_worker.worker import Worker, build_worker

BATCH = 2  # the test book has only 6 chunks, so small batches give it several


class CountingEmbedder(FakeEmbedder):
    """The fake embedder (with its injected errors) that also counts `embed` calls."""

    def __init__(
        self,
        *,
        batch_delay: float = 0.0,
        error_rate: float = 0.0,
        errors: Sequence[Exception | None] | None = None,
        error: Exception | None = None,
    ) -> None:
        super().__init__(
            EMBEDDING_DIM,
            batch_delay=batch_delay,
            error_rate=error_rate,
            errors=errors,
            error=error,
        )
        self.calls = 0

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls += 1
        return await super().embed(texts)


class DyingEmbedder(CountingEmbedder):
    """Embeds `good_batches` batches, then hangs: the point where the test kills the worker."""

    def __init__(self, good_batches: int) -> None:
        super().__init__()
        self.good_batches = good_batches
        self.hung = asyncio.Event()

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if self.calls >= self.good_batches:
            self.hung.set()
            await asyncio.Event().wait()  # never returns; the task is cancelled here
        return await super().embed(texts)


async def add_book(engine: AsyncEngine, storage_key: str = "book.pdf") -> uuid.UUID:
    async with AsyncSession(engine) as session:
        book = Book(title="Sách thử", storage_key=storage_key, owner_id=DEV_OWNER)
        session.add(book)
        await session.flush()
        book_id = book.id
        await session.commit()
        return book_id


@contextlib.asynccontextmanager
async def open_worker(
    database_url: str, storage: Path, embedder: FakeEmbedder
) -> AsyncIterator[Worker]:
    settings = WorkerSettings(
        database_url=database_url, storage_dir=storage, embed_batch_size=BATCH
    )
    w = build_worker(settings, embedder=embedder)
    await init_schema(w)
    try:
        async with w.app.open_async():
            yield w
    finally:
        await w.engine.dispose()


async def run_queue(w: Worker) -> None:
    await w.app.run_worker_async(wait=False, install_signal_handlers=False)


async def make_due(w: Worker) -> None:
    """Skip the retry backoff: make every waiting queue job due now."""
    await w.app.connector.execute_query_async(
        "UPDATE procrastinate_jobs SET scheduled_at = now() WHERE status = 'todo'"
    )


async def chunk_state(engine: AsyncEngine, book_id: uuid.UUID) -> tuple[list[int], int]:
    """The chunk ordinals of a book, and how many of them still have no embedding."""
    async with AsyncSession(engine) as session:
        rows = (
            await session.execute(
                select(Chunk.ordinal, Chunk.embedding.is_(None)).where(Chunk.book_id == book_id)
            )
        ).all()
    return sorted(r[0] for r in rows), sum(1 for r in rows if r[1])


async def job_of(engine: AsyncEngine, job_id: uuid.UUID) -> IngestionJob:
    async with AsyncSession(engine) as session:
        job = await session.get(IngestionJob, job_id)
        assert job is not None
        return job


async def queue_rows(w: Worker, job_id: uuid.UUID) -> list[tuple[int, str]]:
    rows = await w.app.connector.execute_query_all_async(
        "SELECT attempts, status FROM procrastinate_jobs WHERE args->>'job_id' = %(id)s",
        id=str(job_id),
    )
    return [(r["attempts"], r["status"]) for r in rows]


async def expected_chunks(database_url: str, storage: Path) -> int:
    """How many chunks the test book has: a clean run on a throwaway book."""
    async with open_worker(database_url, storage, CountingEmbedder()) as w:
        book_id = await add_book(w.engine)
        await enqueue_ingestion(w.engine, w.app, book_id)
        await run_queue(w)
        ordinals, missing = await chunk_state(w.engine, book_id)
    assert missing == 0
    return len(ordinals)


# --- a worker killed mid-ingestion ------------------------------------------------------------


async def kill_mid_embedding(
    w: Worker, storage: Path, job_id: uuid.UUID, good_batches: int
) -> None:
    """Run the job until `good_batches` batches are committed, then cancel the task.

    Cancelling raises CancelledError, which `run_ingestion` does not catch, so (like a SIGKILL)
    the job row stays `running` and the chunks stay half embedded.
    """
    dying = DyingEmbedder(good_batches)
    task = asyncio.create_task(
        run_ingestion(w.engine, job_id, lambda key: (storage / key).read_bytes(), dying, BATCH)
    )
    await asyncio.wait_for(dying.hung.wait(), timeout=60)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_a_killed_worker_leaves_partial_chunks_and_a_new_run_completes_them(
    database_url: str, storage: Path
) -> None:
    total = await expected_chunks(database_url, storage)
    assert total > 2 * BATCH  # the book must span several batches for a "mid" to exist

    async with open_worker(database_url, storage, CountingEmbedder()) as w:
        book_id = await add_book(w.engine)
        job_id = await enqueue_ingestion(w.engine, w.app, book_id)
        await kill_mid_embedding(w, storage, job_id, good_batches=2)

        ordinals, missing = await chunk_state(w.engine, book_id)
        job = await job_of(w.engine, job_id)
        assert job.status == "running" and job.stage == "embed"  # nobody recorded the death
        assert ordinals == list(range(total))  # all rows exist ...
        assert missing == total - 2 * BATCH  # ... but only two batches have vectors

        # Recovery 1: the sweep (#29) fails the stale job, with a reason the API can show.
        async with AsyncSession(w.engine) as session:
            row = await session.get(IngestionJob, job_id)
            assert row is not None
            row.started_at = datetime.now(UTC) - timedelta(hours=3)
            await session.commit()
        assert await fail_stuck_jobs(w.engine, timedelta(hours=1)) == 1
        swept = await job_of(w.engine, job_id)
        assert swept.status == "failed" and swept.error and "stuck" in swept.error

        # Recovery 2: the user uploads again; a new worker run replaces the partial rows.
        retry_id = await enqueue_ingestion(w.engine, w.app, book_id)
        await run_queue(w)

        assert (await job_of(w.engine, retry_id)).status == "succeeded"
        ordinals, missing = await chunk_state(w.engine, book_id)
        assert ordinals == list(range(total))  # no duplicate, no missing chunk
        assert missing == 0
        async with AsyncSession(w.engine) as session:
            count = (
                await session.execute(select(func.count()).where(Chunk.book_id == book_id))
            ).scalar_one()
        assert count == total


async def test_a_stalled_job_picked_up_again_by_a_new_worker_finishes_cleanly(
    database_url: str, storage: Path
) -> None:
    """A re-delivered job keeps its id: the second run must overwrite the partial rows."""
    total = await expected_chunks(database_url, storage)
    async with open_worker(database_url, storage, CountingEmbedder()) as w:
        book_id = await add_book(w.engine)
        job_id = await enqueue_ingestion(w.engine, w.app, book_id)
        await kill_mid_embedding(w, storage, job_id, good_batches=1)

        await run_ingestion(
            w.engine, job_id, lambda key: (storage / key).read_bytes(), CountingEmbedder(), BATCH
        )

        job = await job_of(w.engine, job_id)
        assert (job.status, job.error) == ("succeeded", None)
        ordinals, missing = await chunk_state(w.engine, book_id)
        assert (ordinals, missing) == (list(range(total)), 0)


# --- transient embedder failures --------------------------------------------------------------


async def test_transient_embedder_failures_back_off_then_succeed(
    database_url: str, storage: Path
) -> None:
    total = await expected_chunks(database_url, storage)
    # One scripted error per embed call: the first two runs fail, the third works.
    embedder = CountingEmbedder(errors=[ConnectionError("model server down"), TimeoutError()])
    async with open_worker(database_url, storage, embedder) as w:
        book_id = await add_book(w.engine)
        job_id = await enqueue_ingestion(w.engine, w.app, book_id)

        await run_queue(w)  # run 1 fails
        job = await job_of(w.engine, job_id)
        assert job.status == "queued" and job.error and "ConnectionError" in job.error
        waiting = await w.app.connector.execute_query_all_async(
            "SELECT scheduled_at > now() AS later FROM procrastinate_jobs"
            " WHERE args->>'job_id' = %(id)s",
            id=str(job_id),
        )
        assert waiting[0]["later"] is True  # backoff: the retry is not due yet

        for _ in range(MAX_RETRIES):
            await make_due(w)
            await run_queue(w)

        job = await job_of(w.engine, job_id)
        assert (job.status, job.error) == ("succeeded", None)
        assert await queue_rows(w, job_id) == [(MAX_RETRIES + 1, "succeeded")]
        ordinals, missing = await chunk_state(w.engine, book_id)
        assert (ordinals, missing) == (list(range(total)), 0)


# --- permanent embedder failures --------------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        ValueError("model rejected the input"),
        HTTPError("http://ollama/api/embed", 400, "Bad Request", Message(), None),
    ],
    ids=["value-error", "http-400"],
)
async def test_a_permanent_embedder_error_fails_once_and_the_api_shows_why(
    database_url: str, storage: Path, error: Exception
) -> None:
    embedder = CountingEmbedder(error_rate=1.0, error=error)
    async with open_worker(database_url, storage, embedder) as w:
        book_id = await add_book(w.engine)
        job_id = await enqueue_ingestion(w.engine, w.app, book_id)

        for _ in range(MAX_RETRIES + 2):  # more passes than there are retries
            await make_due(w)
            await run_queue(w)

        assert embedder.calls == 1  # not retried
        assert await queue_rows(w, job_id) == [(1, "succeeded")]
        job = await job_of(w.engine, job_id)
        assert job.status == "failed" and job.finished_at is not None

        app = create_app(Settings(database_url=database_url))
        async with (
            app.router.lifespan_context(app),
            AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                headers={DEV_USER_HEADER: DEV_OWNER},
            ) as client,
        ):
            body = (await client.get(f"/ingestion-jobs/{job_id}")).json()
    assert body["status"] == "failed"
    assert type(error).__name__ in body["error"]
    assert body["finished_at"] is not None


# --- two workers racing for one job -----------------------------------------------------------


async def test_two_workers_racing_for_one_job_run_it_once(database_url: str, storage: Path) -> None:
    total = await expected_chunks(database_url, storage)
    batches = math.ceil(total / BATCH)
    embedder = CountingEmbedder(batch_delay=0.05)  # shared, so the calls of both are counted
    async with (
        open_worker(database_url, storage, embedder) as first,
        open_worker(database_url, storage, embedder) as second,
    ):
        book_id = await add_book(first.engine)
        job_id = await enqueue_ingestion(first.engine, first.app, book_id)

        await asyncio.gather(run_queue(first), run_queue(second))

        assert embedder.calls == batches  # one run's worth of embedding, not two
        assert await queue_rows(first, job_id) == [(1, "succeeded")]
        job = await job_of(first.engine, job_id)
        assert (job.status, job.error) == ("succeeded", None)
        ordinals, missing = await chunk_state(first.engine, book_id)
        assert (ordinals, missing) == (list(range(total)), 0)
