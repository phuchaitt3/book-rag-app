"""The ingestion pipeline: PDF bytes -> sections and chunks -> embeddings, with progress."""

import asyncio
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from book_rag.chunking import Chunk as ParsedChunk
from book_rag.chunking import chunk_book
from book_rag.parsing import ParsedBook, parse_pdf
from book_rag.providers import Embedder
from book_rag_api.models import EMBEDDING_DIM, Book, Chunk, IngestionJob, Section

log = logging.getLogger(__name__)

ReadPdf = Callable[[str], bytes]

_MAX_ERROR_CHARS = 2000


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
    """Chunks come out in section order, so each one belongs to the first section with its path
    at or after the previous chunk's section (a path can repeat within a book)."""
    rows: list[Chunk] = []
    index = 0
    for chunk in chunks:
        while sections[index].path != chunk.section_path:
            index += 1
        rows.append(
            Chunk(
                id=uuid.uuid4(),
                book_id=book_id,
                section_id=sections[index].id,
                ordinal=chunk.ordinal,
                text=chunk.text,
                page=chunk.page_start,
                section_path=chunk.section_path,
            )
        )
    return rows


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


async def _run(
    engine: AsyncEngine,
    job_id: uuid.UUID,
    read_pdf: ReadPdf,
    embedder: Embedder,
    batch_size: int,
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
    for start in range(0, len(to_embed), batch_size):
        batch = to_embed[start : start + batch_size]
        vectors = await embedder.embed([text for _, text in batch])
        async with AsyncSession(engine) as session:
            await session.execute(
                update(Chunk),
                [{"id": id_, "embedding": v} for (id_, _), v in zip(batch, vectors, strict=True)],
            )
            await session.commit()  # commit per batch so the API shows progress

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
) -> None:
    """Run one job to the end. A failure is recorded on the job (status `failed`), not raised."""
    try:
        await _run(engine, job_id, read_pdf, embedder, batch_size)
    except Exception as exc:
        log.exception("ingestion job %s failed", job_id)
        await _fail(engine, job_id, f"{type(exc).__name__}: {exc}")
