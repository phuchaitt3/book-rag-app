import json
import re
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import TypeAdapter

from book_rag.providers import LLM, FakeLLM, Message
from book_rag.retrieval import RetrievedChunk
from book_rag_api.main import create_app
from book_rag_api.models import Book
from book_rag_api.openapi import document_app, render
from book_rag_api.routers.chat import Citation, DoneEvent, ErrorEvent, TokenEvent, answer_events

# The model for each event's payload, by event name.
EVENT_PAYLOADS: dict[str, TypeAdapter[object]] = {
    "citations": TypeAdapter(list[Citation]),
    "token": TypeAdapter(TokenEvent),
    "done": TypeAdapter(DoneEvent),
    "error": TypeAdapter(ErrorEvent),
}

# The document the web app's types are generated from (ADR 0007).
COMMITTED = Path(__file__).resolve().parents[3] / "apps" / "web" / "src" / "api" / "openapi.json"


def test_committed_document_matches_the_api() -> None:
    assert COMMITTED.read_text(encoding="utf-8") == render(document_app()), (
        "apps/web/src/api/openapi.json is out of date: run `pnpm gen:api` and commit the result"
    )


def test_document_ignores_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    before = render(document_app())
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://other:other@db.example/other")
    monkeypatch.setenv("VECTOR_STORE", "not-a-store")  # invalid: Settings() would raise
    assert render(document_app()) == before


def test_document_describes_the_chat_stream_events() -> None:
    schemas = create_app().openapi()["components"]["schemas"]
    assert {"Citation", "TokenEvent", "DoneEvent", "ErrorEvent"} <= set(schemas)
    assert schemas["TokenEvent"]["required"] == ["text"]


def test_document_types_the_health_replies() -> None:
    paths = create_app().openapi()["paths"]
    ok = paths["/healthz"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert ok == {"$ref": "#/components/schemas/HealthStatus"}
    assert "503" in paths["/readyz"]["get"]["responses"]


class FailingLLM:
    async def stream(self, messages: Sequence[Message]) -> AsyncIterator[str]:
        yield "partial"
        raise RuntimeError("model down")


async def _events(llm: LLM, chunks: list[RetrievedChunk]) -> list[tuple[str, object]]:
    book = Book(id=uuid4(), title="Sách")
    text = "".join([piece async for piece in answer_events(llm, book, "câu hỏi?", chunks)])
    return [
        (block.split("\n")[0].removeprefix("event: "), json.loads(block.split("\n")[1][6:]))
        for block in text.strip().split("\n\n")
    ]


async def test_every_stream_event_matches_its_model() -> None:
    chunk = RetrievedChunk(id=uuid4(), text="văn bản", page=3, section_path="Chương 1")
    answered = await _events(FakeLLM("một hai"), [chunk])
    empty = await _events(FakeLLM("x"), [])
    failed = await _events(FailingLLM(), [chunk])

    seen = set()
    for event, data in [*answered, *empty, *failed]:
        EVENT_PAYLOADS[event].validate_python(data)
        seen.add(event)
    assert seen == set(EVENT_PAYLOADS)


def test_web_client_lists_the_same_events() -> None:
    client = COMMITTED.with_name("client.ts").read_text(encoding="utf-8")
    assert set(re.findall(r'event: "(\w+)"', client)) == set(EVENT_PAYLOADS)
