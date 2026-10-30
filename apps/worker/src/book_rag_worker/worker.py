"""Wires the Procrastinate app, the ingestion task and the providers together."""

import uuid
from dataclasses import dataclass

import procrastinate
from sqlalchemy.ext.asyncio import AsyncEngine

from book_rag.providers import Embedder, FakeEmbedder, OllamaEmbedder
from book_rag_api.db import create_engine
from book_rag_api.jobs import INGEST_TASK, create_queue
from book_rag_api.models import EMBEDDING_DIM
from book_rag_api.storage import S3Storage
from book_rag_worker.config import WorkerSettings
from book_rag_worker.ingest import ReadPdf, run_ingestion
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

    @app.task(name=INGEST_TASK)
    async def ingest_book(job_id: str) -> None:
        await run_ingestion(
            engine, uuid.UUID(job_id), read_pdf, embedder, settings.embed_batch_size
        )

    return Worker(app, engine)
