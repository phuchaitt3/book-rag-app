import asyncio
import io
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import procrastinate
import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from procrastinate import testing
from reportlab.pdfgen import canvas
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from book_rag_api.config import Settings
from book_rag_api.main import create_app
from book_rag_api.models import Book, IngestionJob

ALEMBIC_INI = Path(__file__).parents[1] / "alembic.ini"


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes) -> None:
        self.objects[key] = data

    async def read(self, key: str) -> bytes:
        return self.objects[key]


def make_pdf(pages: int) -> bytes:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    for n in range(pages):
        pdf.drawString(72, 720, f"Page {n + 1}")
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    # psycopg's async mode cannot run on Windows' default ProactorEventLoop.
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with PostgresContainer("pgvector/pgvector:pg17", driver="asyncpg") as pg:
        config = Config(str(ALEMBIC_INI))
        url = pg.get_connection_url()
        config.set_main_option("sqlalchemy.url", url)
        command.upgrade(config, "head")
        yield url


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
async def client(database_url: str, storage: FakeStorage) -> AsyncIterator[AsyncClient]:
    settings = Settings(database_url=database_url, max_upload_bytes=100_000, max_upload_pages=3)
    queue = procrastinate.App(connector=testing.InMemoryConnector())
    app = create_app(settings, storage=storage, queue=queue)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def count(database_url: str, model: type[Book] | type[IngestionJob]) -> int:
    engine = create_async_engine(database_url)
    try:
        async with AsyncSession(engine) as session:
            return await session.scalar(select(func.count()).select_from(model)) or 0
    finally:
        await engine.dispose()


async def test_upload_stores_file_and_queues_ingestion(
    client: AsyncClient, storage: FakeStorage, database_url: str
) -> None:
    pdf = make_pdf(2)
    response = await client.post(
        "/books",
        files={"file": ("my-book.pdf", pdf, "application/pdf")},
        data={"author": "A. Writer"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["book"]["title"] == "my-book"
    assert body["book"]["author"] == "A. Writer"
    assert body["book"]["page_count"] == 2
    assert storage.objects[f"books/{body['book']['id']}/original.pdf"] == pdf

    job = await client.get(f"/ingestion-jobs/{body['job_id']}")
    assert job.status_code == 200
    assert job.json()["status"] == "queued"
    assert await count(database_url, Book) >= 1


async def test_list_books_returns_uploaded_book(client: AsyncClient) -> None:
    uploaded = await client.post(
        "/books", files={"file": ("x.pdf", make_pdf(1), "application/pdf")}, data={"title": "T"}
    )
    listed = await client.get("/books")

    assert listed.status_code == 200
    assert uploaded.json()["book"]["id"] in {b["id"] for b in listed.json()}


async def test_rejects_non_pdf(client: AsyncClient, storage: FakeStorage) -> None:
    response = await client.post("/books", files={"file": ("a.pdf", b"hello", "application/pdf")})

    assert response.status_code == 422
    assert storage.objects == {}


async def test_rejects_corrupt_pdf(client: AsyncClient, storage: FakeStorage) -> None:
    response = await client.post(
        "/books", files={"file": ("a.pdf", b"%PDF-1.7 garbage", "application/pdf")}
    )

    assert response.status_code == 422
    assert storage.objects == {}


async def test_rejects_too_many_pages(client: AsyncClient, storage: FakeStorage) -> None:
    response = await client.post(
        "/books", files={"file": ("a.pdf", make_pdf(4), "application/pdf")}
    )

    assert response.status_code == 413
    assert storage.objects == {}


async def test_rejects_too_large_file(client: AsyncClient, storage: FakeStorage) -> None:
    big = b"%PDF-1.7\n" + b"0" * 100_001
    response = await client.post("/books", files={"file": ("a.pdf", big, "application/pdf")})

    assert response.status_code == 413
    assert storage.objects == {}
