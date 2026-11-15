"""Reading image-only pages in the ingestion job (#272): a fake reader, no tesseract binary."""

import io
import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from book_rag.providers import FakeEmbedder
from book_rag.reading import FakePageReader, RenderedPage
from book_rag_api.auth import DEV_OWNER
from book_rag_api.db import create_engine
from book_rag_api.models import EMBEDDING_DIM, Book, Chunk, IngestionJob, PageRead
from book_rag_worker import ingest
from book_rag_worker.ingest import run_ingestion

BODY = "Người nông dân gieo hạt vào mùa xuân và gặt vào mùa thu. " * 12


def make_book_pdf(kinds: str) -> bytes:
    """One page per letter: 't' a text page, 's' a full-page scan (no text layer)."""
    picture = io.BytesIO()
    Image.new("RGB", (40, 40), (200, 200, 200)).save(picture, format="PNG")
    buffer = io.BytesIO()
    canvas = Canvas(buffer, pageSize=A4)
    for kind in kinds:
        if kind == "t":
            canvas.setFont("Helvetica", 11)
            canvas.drawString(40, 800, BODY[:90])
            canvas.drawString(40, 780, BODY[90:180])
        else:
            picture.seek(0)
            canvas.drawImage(ImageReader(picture), 0, 0, width=595, height=842)
        canvas.showPage()
    canvas.save()
    return buffer.getvalue()


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(database_url)
    yield engine
    await engine.dispose()


async def add_job(engine: AsyncEngine) -> tuple[uuid.UUID, uuid.UUID]:
    async with AsyncSession(engine) as session:
        book = Book(title="Sách quét", storage_key="x.pdf", owner_id=DEV_OWNER)
        session.add(book)
        await session.flush()
        job = IngestionJob(book_id=book.id)
        session.add(job)
        await session.flush()
        ids = (book.id, job.id)
        await session.commit()
    return ids


async def ingest_once(
    engine: AsyncEngine, book_id: uuid.UUID, pdf: bytes, reader: FakePageReader | None
) -> IngestionJob:
    async with AsyncSession(engine) as session:
        job = IngestionJob(book_id=book_id)
        session.add(job)
        await session.flush()
        job_id = job.id
        await session.commit()
    await run_ingestion(
        engine, job_id, lambda _key: pdf, FakeEmbedder(EMBEDDING_DIM), page_reader=reader
    )
    async with AsyncSession(engine) as session:
        done = await session.get(IngestionJob, job_id)
        assert done is not None
        return done


async def stored_reads(engine: AsyncEngine, book_id: uuid.UUID) -> dict[int, str]:
    async with AsyncSession(engine) as session:
        rows = await session.execute(
            select(PageRead.page, PageRead.text).where(PageRead.book_id == book_id)
        )
        return dict(rows.tuples().all())


async def test_all_flagged_book_fails_without_a_reader(engine: AsyncEngine) -> None:
    book_id, _ = await add_job(engine)
    job = await ingest_once(engine, book_id, make_book_pdf("ss"), None)
    assert job.status == "failed"
    assert job.error and "NoTextError" in job.error


async def test_scanned_book_is_read_and_chunked_with_page_numbers(engine: AsyncEngine) -> None:
    book_id, _ = await add_job(engine)
    reader = FakePageReader(lambda n: f"Trang quét {n} ệ ữ ơ. " + BODY)
    job = await ingest_once(engine, book_id, make_book_pdf("ss"), reader)

    assert job.status == "succeeded"
    assert (job.pages_flagged, job.pages_read) == (2, 2)
    reads = await stored_reads(engine, book_id)
    assert set(reads) == {1, 2}
    async with AsyncSession(engine) as session:
        chunks = (
            (await session.execute(select(Chunk).where(Chunk.book_id == book_id))).scalars().all()
        )
    by_page = {c.page: c.text for c in chunks}
    assert set(by_page) >= {1}
    assert "Trang quét 1 ệ ữ ơ." in by_page[1]
    second = [c for c in chunks if "Trang quét 2" in c.text]
    assert second and second[0].page in {1, 2}


async def test_mixed_book_keeps_text_pages_and_reads_the_scan(engine: AsyncEngine) -> None:
    book_id, _ = await add_job(engine)
    reader = FakePageReader(lambda n: f"Phụ lục quét {n}. " + BODY)
    job = await ingest_once(engine, book_id, make_book_pdf("tst"), reader)

    assert job.status == "succeeded"
    assert set(await stored_reads(engine, book_id)) == {2}
    assert reader.calls == 1
    async with AsyncSession(engine) as session:
        texts = (
            (await session.execute(select(Chunk.text).where(Chunk.book_id == book_id)))
            .scalars()
            .all()
        )
    assert any("Phụ lục quét 1" in t for t in texts)


async def test_rerun_skips_pages_already_read_and_adds_no_duplicates(engine: AsyncEngine) -> None:
    book_id, _ = await add_job(engine)
    pdf = make_book_pdf("tss")
    reader = FakePageReader()
    first = await ingest_once(engine, book_id, pdf, reader)
    second = await ingest_once(engine, book_id, pdf, reader)

    assert first.status == second.status == "succeeded"
    assert reader.calls == 2  # the second run read nothing
    assert set(await stored_reads(engine, book_id)) == {2, 3}
    assert second.pages_read == 2
    async with AsyncSession(engine) as session:
        ordinals = (
            (await session.execute(select(Chunk.ordinal).where(Chunk.book_id == book_id)))
            .scalars()
            .all()
        )
    assert sorted(ordinals) == list(range(len(ordinals)))


async def test_a_new_reader_version_reads_again_beside_the_old_rows(engine: AsyncEngine) -> None:
    book_id, _ = await add_job(engine)
    pdf = make_book_pdf("ts")
    await ingest_once(engine, book_id, pdf, FakePageReader(version="1"))
    newer = FakePageReader(version="2")
    await ingest_once(engine, book_id, pdf, newer)
    assert newer.calls == 1
    async with AsyncSession(engine) as session:
        versions = (
            (
                await session.execute(
                    select(PageRead.reader_version).where(PageRead.book_id == book_id)
                )
            )
            .scalars()
            .all()
        )
    assert sorted(versions) == ["1", "2"]


async def test_a_page_that_fails_to_read_is_skipped_then_read_on_the_next_run(
    engine: AsyncEngine,
) -> None:
    book_id, _ = await add_job(engine)
    pdf = make_book_pdf("tss")
    failing = FakePageReader(fail_on=1)
    first = await ingest_once(engine, book_id, pdf, failing)
    assert first.status == "succeeded"
    assert (first.pages_flagged, first.pages_read) == (2, 1)
    assert set(await stored_reads(engine, book_id)) == {3}

    healthy = FakePageReader()
    second = await ingest_once(engine, book_id, pdf, healthy)
    assert healthy.calls == 1  # only page 2 was missing
    assert second.pages_read == 2
    assert set(await stored_reads(engine, book_id)) == {2, 3}


async def test_a_page_that_fails_to_render_is_skipped(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = ingest.render_pages

    def broken_page_2(source: bytes, pages: list[int]) -> Iterator[RenderedPage]:
        for rendered in real(source, pages):
            if rendered.page == 2:
                yield RenderedPage(2, None, "PdfiumError: bad page")
            else:
                yield rendered

    monkeypatch.setattr(ingest, "render_pages", broken_page_2)
    book_id, _ = await add_job(engine)
    reader = FakePageReader()
    job = await ingest_once(engine, book_id, make_book_pdf("tss"), reader)

    assert job.status == "succeeded"
    assert reader.calls == 1
    assert set(await stored_reads(engine, book_id)) == {3}
    assert (job.pages_flagged, job.pages_read) == (2, 1)


async def test_book_whose_every_flagged_page_fails_still_fails(engine: AsyncEngine) -> None:
    book_id, _ = await add_job(engine)
    job = await ingest_once(engine, book_id, make_book_pdf("ss"), FakePageReader(fail_on=1))
    # page 1 failed, page 2 read: the book has text from page 2 and succeeds
    assert job.status == "succeeded"

    other_book, _ = await add_job(engine)
    blank = FakePageReader(text=lambda n: "")  # every page reads as empty text
    empty = await ingest_once(engine, other_book, make_book_pdf("ss"), blank)
    assert empty.status == "failed"
    assert empty.error and "NoTextError" in empty.error
