import io
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import font_roboto
import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from testcontainers.community.postgres import PostgresContainer

from book_rag.providers import FakeEmbedder
from book_rag_api.config import Settings
from book_rag_api.jobs import enqueue_ingestion
from book_rag_api.main import create_app
from book_rag_api.models import EMBEDDING_DIM, Book, Chunk, IngestionJob, Section
from book_rag_worker.__main__ import init_schema
from book_rag_worker.config import WorkerSettings
from book_rag_worker.storage import LocalStorage
from book_rag_worker.worker import Worker, build_worker

ALEMBIC_INI = Path(__file__).parents[2] / "api" / "alembic.ini"
FONT = "Roboto"  # has Vietnamese glyphs; the base-14 fonts do not
pdfmetrics.registerFont(
    TTFont(FONT, str(Path(font_roboto.__file__).parent / "files" / "Roboto-Regular.ttf"))
)

CHAPTERS = [
    ("Chương 1", 1, "Việt Nam là một đất nước nằm ở Đông Nam Á. " * 40),
    ("1.1 Mở đầu", 2, "Người nông dân gieo hạt vào mùa xuân. " * 40),
    ("Chương 2", 1, "Sông Mê Kông chảy qua nhiều tỉnh phía nam. " * 40),
]


def make_pdf() -> bytes:
    """One chapter per page, with an outline."""
    buffer = io.BytesIO()
    canvas = Canvas(buffer, pageSize=A4)
    for number, (title, level, body) in enumerate(CHAPTERS, start=1):
        canvas.bookmarkPage(f"b{number}")
        canvas.addOutlineEntry(title, f"b{number}", level=level - 1)
        canvas.setFont(FONT, 16)
        canvas.drawString(40, 800, title)
        canvas.setFont(FONT, 11)
        y = 770.0
        for line in simpleSplit(body, FONT, 11, 515):
            canvas.drawString(40, y, line)
            y -= 15
        canvas.showPage()
    canvas.save()
    return buffer.getvalue()


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with PostgresContainer("pgvector/pgvector:pg17", driver="asyncpg") as pg:
        url = pg.get_connection_url()
        config = Config(str(ALEMBIC_INI))
        config.set_main_option("sqlalchemy.url", url)
        command.upgrade(config, "head")
        yield url


@pytest.fixture
def storage(tmp_path: Path) -> Path:
    (tmp_path / "book.pdf").write_bytes(make_pdf())
    (tmp_path / "broken.pdf").write_bytes(b"not a pdf")
    return tmp_path


@pytest.fixture
async def worker(database_url: str, storage: Path) -> AsyncIterator[Worker]:
    settings = WorkerSettings(database_url=database_url, storage_dir=storage, embed_batch_size=4)
    w = build_worker(settings, embedder=FakeEmbedder(EMBEDDING_DIM))
    await init_schema(w)
    await init_schema(w)  # a second call must be a no-op
    async with w.app.open_async():
        yield w
    await w.engine.dispose()


async def add_book(engine: AsyncEngine, storage_key: str) -> uuid.UUID:
    async with AsyncSession(engine) as session:
        book = Book(title="Sách thử", storage_key=storage_key)
        session.add(book)
        await session.flush()
        book_id = book.id
        await session.commit()
        return book_id


async def run_queue(w: Worker) -> None:
    await w.app.run_worker_async(wait=False, install_signal_handlers=False)


async def test_job_runs_and_progress_is_readable_through_the_api(
    worker: Worker, database_url: str
) -> None:
    book_id = await add_book(worker.engine, "book.pdf")
    job_id = await enqueue_ingestion(worker.engine, worker.app, book_id)

    app = create_app(Settings(database_url=database_url))
    transport = ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        queued = (await client.get(f"/ingestion-jobs/{job_id}")).json()
        assert queued["status"] == "queued"

        await run_queue(worker)

        done = (await client.get(f"/ingestion-jobs/{job_id}")).json()
        missing = await client.get(f"/ingestion-jobs/{uuid.uuid4()}")
    assert missing.status_code == 404
    assert done["status"] == "succeeded"
    assert done["stage"] is None
    assert done["error"] is None
    assert done["chunks_total"] >= 3
    assert done["chunks_embedded"] == done["chunks_total"]

    async with AsyncSession(worker.engine) as session:
        book = await session.get(Book, book_id)
        assert book is not None
        assert book.page_count == 3
        sections = (
            (await session.execute(select(Section).where(Section.book_id == book_id)))
            .scalars()
            .all()
        )
        chunks = (
            (await session.execute(select(Chunk).where(Chunk.book_id == book_id))).scalars().all()
        )
    by_title = {s.title: s for s in sections}
    assert [s.ordinal for s in sorted(sections, key=lambda s: s.ordinal)] == [0, 1, 2]
    assert by_title["1.1 Mở đầu"].parent_id == by_title["Chương 1"].id
    assert by_title["Chương 2"].parent_id is None
    assert sorted(c.ordinal for c in chunks) == list(range(len(chunks)))
    assert all(c.embedding is not None and c.section_id is not None for c in chunks)
    assert {c.section_path for c in chunks} == {
        "Chương 1",
        "Chương 1 > 1.1 Mở đầu",
        "Chương 2",
    }


async def test_rerun_replaces_chunks_instead_of_duplicating(worker: Worker) -> None:
    book_id = await add_book(worker.engine, "book.pdf")
    for _ in range(2):
        await enqueue_ingestion(worker.engine, worker.app, book_id)
        await run_queue(worker)

    async with AsyncSession(worker.engine) as session:
        ordinals = (
            (await session.execute(select(Chunk.ordinal).where(Chunk.book_id == book_id)))
            .scalars()
            .all()
        )
    assert sorted(ordinals) == list(range(len(ordinals)))


async def test_a_bad_file_marks_the_job_failed(worker: Worker) -> None:
    book_id = await add_book(worker.engine, "broken.pdf")
    job_id = await enqueue_ingestion(worker.engine, worker.app, book_id)
    await run_queue(worker)

    async with AsyncSession(worker.engine) as session:
        job = await session.get(IngestionJob, job_id)
        assert job is not None
        assert job.status == "failed"
        assert job.error
        assert job.finished_at is not None


async def test_queue_tables_live_in_the_same_database(worker: Worker) -> None:
    async with worker.engine.connect() as conn:
        found = (
            await conn.execute(text("SELECT to_regclass('public.procrastinate_jobs')"))
        ).scalar()
    assert found is not None


def test_storage_refuses_keys_outside_its_directory(tmp_path: Path) -> None:
    (tmp_path / "root").mkdir()
    (tmp_path / "secret.txt").write_text("x")
    storage = LocalStorage(tmp_path / "root")
    with pytest.raises(ValueError, match="outside"):
        storage.read("../secret.txt")


async def test_two_jobs_for_one_book_both_finish(worker: Worker) -> None:
    book_id = await add_book(worker.engine, "book.pdf")
    first = await enqueue_ingestion(worker.engine, worker.app, book_id)
    second = await enqueue_ingestion(worker.engine, worker.app, book_id)
    await run_queue(worker)
    await run_queue(worker)  # the lock may defer the second job to a later pass

    async with AsyncSession(worker.engine) as session:
        statuses = [
            (await session.get(IngestionJob, job_id)).status  # type: ignore[union-attr]
            for job_id in (first, second)
        ]
        ordinals = (
            (await session.execute(select(Chunk.ordinal).where(Chunk.book_id == book_id)))
            .scalars()
            .all()
        )
    assert statuses == ["succeeded", "succeeded"]
    assert sorted(ordinals) == list(range(len(ordinals)))
