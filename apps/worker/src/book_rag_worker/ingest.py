"""The ingestion pipeline: PDF bytes -> sections and chunks -> embeddings, with progress."""

import asyncio
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from urllib.error import HTTPError, URLError

from sqlalchemy import delete, or_, update
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from book_rag.chunking import Chunk as ParsedChunk
from book_rag.chunking import chunk_book
from book_rag.parsing import ParsedBook, parse_pdf
from book_rag.providers import Embedder
from book_rag_api.models import EMBEDDING_DIM, Book, Chunk, IngestionJob, Section
from book_rag_api.qdrant_index import QdrantVectorIndex

log = logging.getLogger(__name__)

ReadPdf = Callable[[str], bytes]

_MAX_ERROR_CHARS = 2000

# A transient failure is retried this many times (so a job runs at most 3 times). A re-run
# replaces the rows of the earlier attempt, so a retry is safe.
MAX_RETRIES = 2


class TransientIngestionError(Exception):
    """A failure worth retrying (Ollama or the database was briefly unreachable)."""


def is_transient(exc: BaseException) -> bool:
    """Connection errors, timeouts and server-side HTTP errors; bad input is not transient."""
    if isinstance(exc, HTTPError):
        return exc.code >= 500 or exc.code == 429
    return isinstance(
        exc, ConnectionError | TimeoutError | URLError | OperationalError | InterfaceError
    )


def _now() -> datetime:
    return datetime.now(UTC)


def _section_rows(book_id: uuid.UUID, parsed: ParsedBook) -> list[Section]:
    rows: list[Section] = []
    stack: list[Section] = []  # open ancestors, shallowest first
    for ordinal, section in enumerate(parsed.sections):
        while stack and stack[-1].level >= section.level:
            stack.pop()
        pages = [seg.page for seg in section.segments]
        row = Section(
            id=uuid.uuid4(),
            book_id=book_id,
            parent_id=stack[-1].id if stack else None,
            title=section.title,
            path=section.path,
            level=section.level,
            ordinal=ordinal,
            page_start=min(pages),
            page_end=max(pages),
        )
        rows.append(row)
        stack.append(row)
    return rows


def _chunk_rows(
    book_id: uuid.UUID, sections: list[Section], chunks: list[ParsedChunk]
) -> list[Chunk]:
    return [
        Chunk(
            id=uuid.uuid4(),
            book_id=book_id,
            section_id=sections[chunk.section_index].id,
            ordinal=chunk.ordinal,
            text=chunk.text,
            page=chunk.page_start,
            section_path=chunk.section_path,
        )
        for chunk in chunks
    ]


async def _set_stage(engine: AsyncEngine, job_id: uuid.UUID, stage: str) -> None:
    async with AsyncSession(engine) as session:
        await session.execute(
            update(IngestionJob).where(IngestionJob.id == job_id).values(stage=stage)
        )
        await session.commit()


async def _fail(engine: AsyncEngine, job_id: uuid.UUID, error: str) -> None:
    async with AsyncSession(engine) as session:
        await session.execute(
            update(IngestionJob)
            .where(IngestionJob.id == job_id)
            .values(status="failed", error=error[:_MAX_ERROR_CHARS], finished_at=_now())
        )
        await session.commit()


async def _requeue(engine: AsyncEngine, job_id: uuid.UUID, error: str) -> None:
    async with AsyncSession(engine) as session:
        await session.execute(
            update(IngestionJob)
            .where(IngestionJob.id == job_id)
            .values(status="queued", stage=None, error=error[:_MAX_ERROR_CHARS])
        )
        await session.commit()


async def fail_stuck_jobs(engine: AsyncEngine, older_than: timedelta) -> int:
    """Fail jobs left `queued` since creation, or `running` since start, longer than `older_than`.

    Covers a failed `defer_async` and a killed worker. If the worker still picks such a job up
    later, `_run` sets it to `running` again, so the sweep never blocks a live job for good.
    """
    cutoff = _now() - older_than
    async with AsyncSession(engine) as session:
        result = await session.execute(
            update(IngestionJob)
            .where(
                or_(
                    (IngestionJob.status == "queued") & (IngestionJob.created_at < cutoff),
                    (IngestionJob.status == "running") & (IngestionJob.started_at < cutoff),
                )
            )
            .values(
                status="failed",
                error=f"stuck: no progress for over {older_than}",
                finished_at=_now(),
            )
        )
        await session.commit()
        return int(result.rowcount)  # type: ignore[attr-defined]


async def _run(
    engine: AsyncEngine,
    job_id: uuid.UUID,
    read_pdf: ReadPdf,
    embedder: Embedder,
    batch_size: int,
    index: QdrantVectorIndex | None = None,
) -> None:
    if embedder.dimension != EMBEDDING_DIM:
        raise ValueError(f"embedder dimension {embedder.dimension} != column {EMBEDDING_DIM}")

    async with AsyncSession(engine) as session:
        job = await session.get(IngestionJob, job_id)
        if job is None:
            raise LookupError(f"ingestion job {job_id} not found")
        book = await session.get(Book, job.book_id)
        if book is None or not book.storage_key:
            raise LookupError(f"book of job {job_id} has no uploaded file")
        book_id, title, storage_key = book.id, book.title, book.storage_key
        job.status, job.stage, job.error = "running", "parse", None
        job.started_at, job.finished_at = _now(), None
        await session.commit()

    parsed = await asyncio.to_thread(lambda: parse_pdf(read_pdf(storage_key), title=title))

    await _set_stage(engine, job_id, "chunk")
    chunks = await asyncio.to_thread(chunk_book, parsed)
    sections = _section_rows(book_id, parsed)
    chunk_rows = _chunk_rows(book_id, sections, chunks)
    to_embed = [(c.id, c.text) for c in chunk_rows]  # plain values: the ORM rows expire on commit
    # Replace what an earlier attempt stored, so a re-run never duplicates ordinals.
    async with AsyncSession(engine) as session:
        await session.execute(delete(Chunk).where(Chunk.book_id == book_id))
        await session.execute(delete(Section).where(Section.book_id == book_id))
        await session.execute(
            update(Book).where(Book.id == book_id).values(page_count=parsed.page_count)
        )
        session.add_all(sections)
        await session.flush()  # sections first: chunks reference them
        session.add_all(chunk_rows)
        await session.commit()

    await _set_stage(engine, job_id, "embed")
    if index is not None:
        await index.delete_book(book_id)  # a re-run replaced the chunk ids, so drop the old points
    for start in range(0, len(to_embed), batch_size):
        batch = to_embed[start : start + batch_size]
        vectors = await embedder.embed([text for _, text in batch])
        async with AsyncSession(engine) as session:
            await session.execute(
                update(Chunk),
                [{"id": id_, "embedding": v} for (id_, _), v in zip(batch, vectors, strict=True)],
            )
            await session.commit()  # commit per batch so the API shows progress
        if index is not None:
            # After the commit, so Qdrant never holds a vector Postgres lost. An upsert is
            # idempotent, so a retried batch is harmless.
            await index.upsert(
                book_id, [(id_, v) for (id_, _), v in zip(batch, vectors, strict=True)]
            )

    async with AsyncSession(engine) as session:
        await session.execute(
            update(IngestionJob)
            .where(IngestionJob.id == job_id)
            .values(status="succeeded", stage=None, finished_at=_now())
        )
        await session.commit()


async def run_ingestion(
    engine: AsyncEngine,
    job_id: uuid.UUID,
    read_pdf: ReadPdf,
    embedder: Embedder,
    batch_size: int = 32,
    attempts: int = MAX_RETRIES,
    index: QdrantVectorIndex | None = None,
) -> None:
    """Run one job to the end. A failure is recorded on the job (status `failed`), not raised.

    `attempts` is how many times the job has run before. A transient failure with retries left
    puts the job back to `queued` and raises `TransientIngestionError` for the queue to retry;
    the default means no retries are left.
    """
    try:
        await _run(engine, job_id, read_pdf, embedder, batch_size, index)
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        if is_transient(exc) and attempts < MAX_RETRIES:
            log.warning("ingestion job %s hit a transient error, will retry: %s", job_id, message)
            await _requeue(engine, job_id, f"retrying after {message}")
            raise TransientIngestionError(message) from exc
        log.exception("ingestion job %s failed", job_id)
        await _fail(engine, job_id, message)
