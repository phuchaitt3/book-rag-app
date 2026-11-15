"""Ingestion spans (#225): one `ingest.job` span with a child per stage."""

import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy.ext.asyncio import AsyncSession

from book_rag.providers import FakeEmbedder
from book_rag_api.auth import DEV_OWNER
from book_rag_api.models import EMBEDDING_DIM, Book, IngestionJob
from book_rag_api.tracing import OtelTracer, build_tracing
from book_rag_worker import ingest
from book_rag_worker.config import WorkerSettings
from book_rag_worker.ingest import run_ingestion
from book_rag_worker.worker import Worker, build_worker


@pytest.fixture
async def worker(database_url: str, storage: Path) -> AsyncIterator[Worker]:
    w = build_worker(
        WorkerSettings(database_url=database_url, storage_dir=storage),
        embedder=FakeEmbedder(EMBEDDING_DIM),
    )
    yield w
    await w.engine.dispose()


@pytest.fixture
def spans() -> Iterator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = build_tracing(None, exporter=exporter)
    assert provider is not None
    ingest.set_tracer(OtelTracer.from_provider(provider))
    yield exporter
    ingest.set_tracer(None)


async def test_a_job_has_one_span_per_stage_under_the_job_span(
    worker: Worker, spans: InMemorySpanExporter, storage: Path
) -> None:
    async with AsyncSession(worker.engine) as session:
        book = Book(title="Sách thử", storage_key="book.pdf", owner_id=DEV_OWNER)
        session.add(book)
        await session.flush()
        job = IngestionJob(book_id=book.id)
        session.add(job)
        await session.flush()
        job_id: uuid.UUID = job.id
        await session.commit()

    pdf = (storage / "book.pdf").read_bytes()
    await run_ingestion(worker.engine, job_id, lambda _key: pdf, FakeEmbedder(EMBEDDING_DIM))

    finished = {s.name: s for s in spans.get_finished_spans()}
    stages = {"ingest.parse", "ingest.chunk", "ingest.store", "ingest.embed"}
    assert set(finished) == {"ingest.job", *stages}
    job_span = finished["ingest.job"]
    assert job_span.parent is None
    assert job_span.attributes is not None
    assert job_span.attributes["job_id"] == str(job_id)
    for name in stages:
        parent = finished[name].parent
        assert parent is not None
        assert parent.span_id == job_span.context.span_id
    chunk_attributes = finished["ingest.chunk"].attributes
    assert chunk_attributes is not None
    assert chunk_attributes["chunks"] >= 3  # type: ignore[operator]
