import asyncio
import json
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import UUID, uuid4

import procrastinate
import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from procrastinate import testing
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from book_rag.providers import FakeEmbedder, FakeLLM, Message
from book_rag.retrieval import RetrievedChunk
from book_rag_api.config import Settings
from book_rag_api.main import create_app
from book_rag_api.models import EMBEDDING_DIM, Book, Chunk, IngestionJob
from book_rag_api.prompts import NO_PASSAGES_REPLY, build_messages
from book_rag_api.routers.chat import sse

ALEMBIC_INI = Path(__file__).parents[1] / "alembic.ini"

TEXTS = [
    ("Sông Hồng chảy qua Hà Nội", "Chương 1 > Sông ngòi", 3),
    ("Núi Fansipan cao nhất Đông Dương", "Chương 2 > Núi", 7),
]


class BrokenLLM:
    async def stream(self, messages: list[Message]) -> AsyncIterator[str]:
        yield "partial"
        raise RuntimeError("model down")


def parse_sse(text: str) -> list[tuple[str, object]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = block.split("\n")
        events.append(
            (lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: ")))
        )
    return events


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
async def book_id(database_url: str) -> UUID:
    engine = create_async_engine(database_url)
    embedder = FakeEmbedder(EMBEDDING_DIM)
    vectors = await embedder.embed([t for t, _, _ in TEXTS])
    book = Book(id=uuid4(), title="Địa lý Việt Nam")
    async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
        session.add(book)
        await session.flush()
        session.add_all(
            Chunk(book_id=book.id, ordinal=i, text=t, page=p, section_path=s, embedding=v)
            for i, ((t, s, p), v) in enumerate(zip(TEXTS, vectors, strict=True))
        )
    await engine.dispose()
    return book.id


async def make_client(database_url: str, llm: object) -> AsyncIterator[AsyncClient]:
    app = create_app(
        Settings(database_url=database_url),
        storage=object(),  # type: ignore[arg-type]
        queue=procrastinate.App(connector=testing.InMemoryConnector()),
        llm=llm,  # type: ignore[arg-type]
        embedder=FakeEmbedder(EMBEDDING_DIM),
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        yield c


@pytest.fixture
async def client(database_url: str) -> AsyncIterator[AsyncClient]:
    async for c in make_client(database_url, FakeLLM("Sông Hồng chảy qua Hà Nội [1]")):
        yield c


async def test_streams_citations_then_tokens_then_done(client: AsyncClient, book_id: UUID) -> None:
    response = await client.post(f"/books/{book_id}/chat", json={"question": "sông Hồng ở đâu"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    names = [name for name, _ in events]
    assert names[0] == "citations"
    assert names[-1] == "done"
    assert set(names[1:-1]) == {"token"}
    answer = "".join(data["text"] for name, data in events if name == "token")  # type: ignore[index]
    assert answer == "Sông Hồng chảy qua Hà Nội [1]"


async def test_citations_name_book_section_and_page(client: AsyncClient, book_id: UUID) -> None:
    response = await client.post(f"/books/{book_id}/chat", json={"question": "sông Hồng Hà Nội"})

    citations = parse_sse(response.text)[0][1]
    assert isinstance(citations, list)
    first = citations[0]
    assert first["number"] == 1
    assert first["book_id"] == str(book_id)
    assert first["book_title"] == "Địa lý Việt Nam"
    assert first["section"] == "Chương 1 > Sông ngòi"
    assert first["page"] == 3


async def test_unknown_book_is_404(client: AsyncClient) -> None:
    response = await client.post(f"/books/{uuid4()}/chat", json={"question": "hi"})

    assert response.status_code == 404


@pytest.mark.parametrize("job_status", ["queued", "running", "failed"])
async def test_book_whose_latest_ingestion_has_not_succeeded_is_409(
    client: AsyncClient, database_url: str, book_id: UUID, job_status: str
) -> None:
    engine = create_async_engine(database_url)
    # Two transactions, so `now()` gives the re-run a later `created_at`.
    for status in ("succeeded", job_status):
        async with AsyncSession(engine) as session, session.begin():
            session.add(IngestionJob(book_id=book_id, status=status))
    await engine.dispose()

    response = await client.post(f"/books/{book_id}/chat", json={"question": "sông Hồng"})

    assert response.status_code == 409
    assert job_status in response.json()["detail"]


async def test_book_whose_latest_ingestion_succeeded_is_answered(
    client: AsyncClient, database_url: str, book_id: UUID
) -> None:
    engine = create_async_engine(database_url)
    async with AsyncSession(engine) as session, session.begin():
        session.add(IngestionJob(book_id=book_id, status="succeeded"))
    await engine.dispose()

    response = await client.post(f"/books/{book_id}/chat", json={"question": "sông Hồng"})

    assert response.status_code == 200


async def test_empty_question_is_rejected(client: AsyncClient, book_id: UUID) -> None:
    response = await client.post(f"/books/{book_id}/chat", json={"question": ""})

    assert response.status_code == 422


async def test_model_failure_ends_with_error_event(database_url: str, book_id: UUID) -> None:
    async for client in make_client(database_url, BrokenLLM()):
        response = await client.post(f"/books/{book_id}/chat", json={"question": "sông Hồng"})

    names = [name for name, _ in parse_sse(response.text)]
    assert names == ["citations", "token", "error"]


async def test_book_without_chunks_replies_without_calling_the_model(
    database_url: str,
) -> None:
    engine = create_async_engine(database_url)
    empty = Book(id=uuid4(), title="Empty")
    async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
        session.add(empty)
    await engine.dispose()

    async for client in make_client(database_url, BrokenLLM()):
        response = await client.post(f"/books/{empty.id}/chat", json={"question": "anything"})

    assert parse_sse(response.text) == [
        ("citations", []),
        ("token", {"text": NO_PASSAGES_REPLY}),
        ("done", {}),
    ]


def test_prompt_numbers_passages_and_carries_the_question() -> None:
    chunks = [
        RetrievedChunk(id=uuid4(), text="alpha", page=4, section_path="Ch 1"),
        RetrievedChunk(id=uuid4(), text="beta", page=None, section_path=None),
    ]

    system, user = build_messages("why?", "My Book", chunks)

    assert system.role == "system"
    assert "[1] (Ch 1, page 4)\nalpha" in user.content
    assert "[2]\nbeta" in user.content
    assert "Book: My Book" in user.content
    assert user.content.endswith("Question: why?")


def test_sse_keeps_unicode_readable() -> None:
    assert sse("token", {"text": "Hà Nội"}) == 'event: token\ndata: {"text": "Hà Nội"}\n\n'
