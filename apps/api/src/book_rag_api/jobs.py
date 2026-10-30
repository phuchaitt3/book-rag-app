"""Ingestion jobs: enqueue a book for the worker, and read a job's progress."""

import uuid
from datetime import datetime
from typing import Annotated

import procrastinate
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from book_rag_api.db import to_asyncpg_url
from book_rag_api.models import Chunk, IngestionJob

# The task the worker registers under this name; the API defers it without importing the worker.
INGEST_TASK = "ingest_book"


def to_libpq_dsn(database_url: str) -> str:
    """Procrastinate talks to Postgres through psycopg, which wants a libpq URL."""
    url = to_asyncpg_url(database_url)
    query = {("sslmode" if k == "ssl" else k): v for k, v in url.query.items()}
    return url.set(drivername="postgresql", query=query).render_as_string(hide_password=False)


def create_queue(database_url: str) -> procrastinate.App:
    """The Procrastinate app, backed by the same Postgres as the data (no Redis)."""
    connector = procrastinate.PsycopgConnector(conninfo=to_libpq_dsn(database_url))
    return procrastinate.App(connector=connector)


async def enqueue_ingestion(
    engine: AsyncEngine, queue: procrastinate.App, book_id: uuid.UUID
) -> uuid.UUID:
    """Record a queued job for `book_id` and hand it to the worker. The queue must be open."""
    async with AsyncSession(engine) as session:
        job = IngestionJob(book_id=book_id)
        session.add(job)
        await session.flush()
        job_id = job.id
        await session.commit()
    # One lock per book: two jobs for the same book never run at the same time.
    await queue.configure_task(INGEST_TASK, lock=str(book_id)).defer_async(job_id=str(job_id))
    return job_id


class IngestionProgress(BaseModel):
    id: uuid.UUID
    book_id: uuid.UUID
    status: str
    stage: str | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    chunks_total: int
    chunks_embedded: int


router = APIRouter(tags=["ingestion"])


def _engine(request: Request) -> AsyncEngine:
    engine: AsyncEngine = request.app.state.engine
    return engine


@router.get("/ingestion-jobs/{job_id}")
async def get_ingestion_job(
    job_id: uuid.UUID, engine: Annotated[AsyncEngine, Depends(_engine)]
) -> IngestionProgress:
    """Status, current stage and, while embedding, how many chunks are done."""
    async with AsyncSession(engine) as session:
        job = await session.get(IngestionJob, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="ingestion job not found")
        total, embedded = (
            await session.execute(
                select(func.count(), func.count(Chunk.embedding)).where(
                    Chunk.book_id == job.book_id
                )
            )
        ).one()
    return IngestionProgress(
        id=job.id,
        book_id=job.book_id,
        status=job.status,
        stage=job.stage,
        error=job.error,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        chunks_total=total,
        chunks_embedded=embedded,
    )
