"""Tracing (#225): the span tree of one chat request, and nothing created when tracing is off."""

import asyncio
import json
import logging
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import UUID, uuid4

import procrastinate
import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind
from procrastinate import testing
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from book_rag.providers import FakeEmbedder, FakeLLM
from book_rag_api import tracing
from book_rag_api.auth import DEV_OWNER, DEV_USER_HEADER
from book_rag_api.config import Settings
from book_rag_api.main import create_app
from book_rag_api.models import EMBEDDING_DIM, Book, Chunk
from book_rag_api.observability import JsonFormatter

ALEMBIC_INI = Path(__file__).parents[1] / "alembic.ini"
TEXTS = [
    ("Sông Hồng chảy qua Hà Nội", "Chương 1 > Sông ngòi", 3),
    ("Núi Fansipan cao nhất Đông Dương", "Chương 2 > Núi", 7),
]


def test_tracing_is_off_without_an_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(endpoint: str) -> object:
        raise AssertionError("an exporter was created while tracing is off")

    monkeypatch.setattr(tracing, "_otlp_exporter", forbidden)

    assert tracing.build_tracing(None) is None
    assert tracing.build_tracing("") is None
    app = create_app(Settings(otel_exporter_otlp_endpoint=None))
    assert app.user_middleware  # the app is built...
    assert not any("OpenTelemetry" in repr(m.cls) for m in app.user_middleware)  # ...uninstrumented


def test_endpoint_turns_tracing_on_with_an_otlp_http_exporter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[str] = []
    in_memory = InMemorySpanExporter()

    def fake(endpoint: str) -> InMemorySpanExporter:
        asked.append(endpoint)
        return in_memory

    monkeypatch.setattr(tracing, "_otlp_exporter", fake)

    provider = tracing.build_tracing("http://localhost:4318")

    assert provider is not None
    assert asked == ["http://localhost:4318"]
    provider.shutdown()


def test_otlp_exporter_posts_to_the_traces_path() -> None:
    exporter = tracing._otlp_exporter("http://localhost:4318/")
    assert exporter._endpoint == "http://localhost:4318/v1/traces"  # type: ignore[attr-defined]
    exporter.shutdown()


def test_log_lines_carry_trace_id_only_inside_a_span() -> None:
    provider = tracing.build_tracing(None, exporter=InMemorySpanExporter())
    assert provider is not None
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "hello", None, None)

    assert "trace_id" not in json.loads(JsonFormatter().format(record))
    with provider.get_tracer("t").start_as_current_span("s") as span:
        line = json.loads(JsonFormatter().format(record))
    assert line["trace_id"] == f"{span.get_span_context().trace_id:032x}"


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
    vectors = await FakeEmbedder(EMBEDDING_DIM).embed([t for t, _, _ in TEXTS])
    book = Book(id=uuid4(), title="Địa lý Việt Nam", owner_id=DEV_OWNER)
    async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
        session.add(book)
        await session.flush()
        session.add_all(
            Chunk(book_id=book.id, ordinal=i, text=t, page=p, section_path=s, embedding=v)
            for i, ((t, s, p), v) in enumerate(zip(TEXTS, vectors, strict=True))
        )
    await engine.dispose()
    return book.id


@pytest.fixture
async def traced_client(
    database_url: str,
) -> AsyncIterator[tuple[AsyncClient, InMemorySpanExporter]]:
    exporter = InMemorySpanExporter()
    app = create_app(
        Settings(database_url=database_url, reranker_provider="fake"),
        storage=object(),  # type: ignore[arg-type]
        queue=procrastinate.App(connector=testing.InMemoryConnector()),
        llm=FakeLLM("Sông Hồng chảy qua Hà Nội [1]"),
        embedder=FakeEmbedder(EMBEDDING_DIM),
        span_exporter=exporter,
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={DEV_USER_HEADER: DEV_OWNER},
        ) as client,
    ):
        yield client, exporter


def by_id(spans: tuple[ReadableSpan, ...]) -> dict[int, ReadableSpan]:
    return {s.context.span_id: s for s in spans}


def parent_name(span: ReadableSpan, spans: dict[int, ReadableSpan]) -> str | None:
    return spans[span.parent.span_id].name if span.parent is not None else None


async def test_one_chat_request_makes_the_documented_span_tree(
    traced_client: tuple[AsyncClient, InMemorySpanExporter], book_id: UUID
) -> None:
    client, exporter = traced_client

    response = await client.post(
        f"/books/{book_id}/chat", json={"question": "sông Hồng ở đâu", "top_k": 2}
    )

    assert response.status_code == 200
    finished = exporter.get_finished_spans()
    spans = by_id(finished)
    manual = {
        "embed_query",
        "vector_search",
        "lexical_search",
        "fuse",
        "rerank",
        "llm.stream",
        "llm.first_token",
    }
    named = {s.name: s for s in finished if s.name in manual}
    assert set(named) == manual
    request_span = next(s for s in finished if s.kind == SpanKind.SERVER)
    assert request_span.name == "POST /books/{book_id}/chat"
    assert request_span.parent is None
    # Every span of the request belongs to one trace.
    assert {s.context.trace_id for s in finished} == {request_span.context.trace_id}

    for name in ("embed_query", "vector_search", "lexical_search", "fuse", "rerank", "llm.stream"):
        assert parent_name(named[name], spans) == request_span.name, name
    assert parent_name(named["llm.first_token"], spans) == "llm.stream"
    # The two searches run at once; the SQL statements they issue are their children.
    sql = [s for s in finished if s.attributes and "db.system" in s.attributes]
    assert sql
    assert {parent_name(s, spans) for s in sql} >= {"vector_search", "lexical_search"}

    book = str(book_id)
    assert named["vector_search"].attributes == {"book_id": book, "k": 30, "candidates": 2}
    assert named["lexical_search"].attributes == {"book_id": book, "k": 30, "candidates": 1}
    fuse = named["fuse"].attributes
    assert fuse is not None
    assert fuse["vector_candidates"] == 2
    assert fuse["lexical_candidates"] == 1
    assert fuse["top_k"] == 2
    rerank = named["rerank"].attributes
    assert rerank is not None
    assert rerank["fallback"] is False
    assert rerank["candidates"] == 2
    stream = named["llm.stream"].attributes
    assert stream is not None
    assert stream["book_id"] == book
    assert stream["pieces"] >= 1
