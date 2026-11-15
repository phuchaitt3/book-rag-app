"""Export the spans of one chat request to JSON (#225): docs/operations/traces/chat-request.json.

Needs Docker (a throwaway pgvector container, as in the tests) and no model: the fake embedder,
LLM and reranker answer, and an in-memory span exporter collects the spans. Timings are those of
the fakes on the machine that ran it, so they show the shape of the trace, not real latency.

  uv run python scripts/export_chat_trace.py
"""

import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

import procrastinate
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from procrastinate import testing
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from book_rag.providers import FakeEmbedder, FakeLLM
from book_rag_api.auth import DEV_OWNER, DEV_USER_HEADER
from book_rag_api.config import Settings
from book_rag_api.main import create_app
from book_rag_api.models import EMBEDDING_DIM, Book, Chunk

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "operations" / "traces" / "chat-request.json"
TEXTS = [
    ("Sông Hồng chảy qua Hà Nội", "Chương 1 > Sông ngòi", 3),
    ("Núi Fansipan cao nhất Đông Dương", "Chương 2 > Núi", 7),
]


def as_json(span: ReadableSpan) -> dict[str, object]:
    context = span.context
    assert span.start_time is not None
    assert span.end_time is not None
    return {
        "name": span.name,
        "trace_id": f"{context.trace_id:032x}",
        "span_id": f"{context.span_id:016x}",
        "parent_span_id": f"{span.parent.span_id:016x}" if span.parent else None,
        "kind": span.kind.name,
        "start_unix_nano": span.start_time,
        "duration_ms": round((span.end_time - span.start_time) / 1e6, 3),
        "status": span.status.status_code.name,
        "attributes": dict(span.attributes or {}),
    }


async def chat_trace(database_url: str) -> list[dict[str, object]]:
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
        response = await client.post(
            f"/books/{book.id}/chat", json={"question": "sông Hồng ở đâu", "top_k": 2}
        )
        response.raise_for_status()
    spans = sorted(exporter.get_finished_spans(), key=lambda s: s.start_time or 0)
    return [as_json(s) for s in spans]


def main() -> None:
    if sys.platform == "win32":  # psycopg's async mode needs a selector loop
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    with PostgresContainer("pgvector/pgvector:pg17", driver="asyncpg") as pg:
        url = pg.get_connection_url()
        config = Config(str(ROOT / "apps" / "api" / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", url)
        command.upgrade(config, "head")
        spans = asyncio.run(chat_trace(url))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"spans": spans}, indent=2, ensure_ascii=False) + "\n", "utf-8")
    print(f"wrote {len(spans)} spans to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
