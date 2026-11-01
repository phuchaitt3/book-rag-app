"""Wires the Procrastinate app, the ingestion task and the providers together."""

import uuid
from dataclasses import dataclass
from datetime import timedelta

import procrastinate
from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import AsyncEngine

from book_rag.providers import Embedder, FakeEmbedder, OllamaEmbedder
from book_rag_api.db import create_engine
from book_rag_api.jobs import INGEST_TASK, create_queue
from book_rag_api.models import EMBEDDING_DIM
from book_rag_api.qdrant_index import QdrantVectorIndex
from book_rag_api.storage import S3Storage
from book_rag_worker.config import WorkerSettings
from book_rag_worker.ingest import (
    MAX_RETRIES,
    ReadPdf,
    TransientIngestionError,
    fail_stuck_jobs,
    run_ingestion,
)
from book_rag_worker.storage import LocalStorage


def create_reader(settings: WorkerSettings) -> ReadPdf:
    if settings.s3_endpoint_url:
        return S3Storage(
            endpoint_url=settings.s3_endpoint_url,
            bucket=settings.s3_bucket,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            region=settings.s3_region,
        ).read_blocking
    return LocalStorage(settings.storage_dir).read


def create_embedder(settings: WorkerSettings) -> Embedder:
    if settings.embedding_provider == "fake":
        return FakeEmbedder(EMBEDDING_DIM)
    if settings.embedding_provider == "ollama":
        return OllamaEmbedder(settings.embedding_model, EMBEDDING_DIM, settings.ollama_url)
    raise ValueError(f"unknown embedding provider {settings.embedding_provider!r}")


def create_index(settings: WorkerSettings) -> QdrantVectorIndex | None:
    """The Qdrant copy of the vectors, only when the experiment is switched on (ADR 0008)."""
    if settings.vector_store != "qdrant":
        return None
    client = AsyncQdrantClient(url=settings.qdrant_url)
    return QdrantVectorIndex(client, settings.qdrant_collection)


@dataclass(frozen=True, slots=True)
class Worker:
    app: procrastinate.App
    engine: AsyncEngine


def build_worker(
    settings: WorkerSettings,
    *,
    embedder: Embedder | None = None,
    read_pdf: ReadPdf | None = None,
) -> Worker:
    """Providers default to the ones in `settings`; tests pass fakes."""
    app = create_queue(settings.database_url)
    engine = create_engine(settings.database_url)
    embedder = embedder or create_embedder(settings)
    read_pdf = read_pdf or create_reader(settings)
    index = create_index(settings)

    # Only transient errors are retried; a bad PDF fails at once (run_ingestion records it).
    retry = procrastinate.RetryStrategy(
        max_attempts=MAX_RETRIES, exponential_wait=3, retry_exceptions=[TransientIngestionError]
    )

    @app.task(name=INGEST_TASK, pass_context=True, retry=retry)
    async def ingest_book(context: procrastinate.JobContext, job_id: str) -> None:
        await run_ingestion(
            engine,
            uuid.UUID(job_id),
            read_pdf,
            embedder,
            settings.embed_batch_size,
            attempts=context.job.attempts,
            index=index,
        )

    @app.periodic(cron="*/5 * * * *")
    @app.task(name="fail_stuck_jobs")
    async def sweep_stuck_jobs(timestamp: int) -> None:
        await fail_stuck_jobs(engine, timedelta(minutes=settings.stuck_job_minutes))

    return Worker(app, engine)
