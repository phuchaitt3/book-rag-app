from pathlib import Path

from book_rag_api.main import create_app
from book_rag_api.openapi import render

# The document the web app's types are generated from (ADR 0007).
COMMITTED = Path(__file__).resolve().parents[3] / "apps" / "web" / "src" / "api" / "openapi.json"


def test_committed_document_matches_the_api() -> None:
    assert COMMITTED.read_text(encoding="utf-8") == render(create_app()), (
        "apps/web/src/api/openapi.json is out of date: run `pnpm gen:api` and commit the result"
    )


def test_document_describes_the_chat_stream_events() -> None:
    schemas = create_app().openapi()["components"]["schemas"]
    assert {"Citation", "TokenEvent", "DoneEvent", "ErrorEvent"} <= set(schemas)
    assert schemas["TokenEvent"]["required"] == ["text"]


def test_document_types_the_health_replies() -> None:
    paths = create_app().openapi()["paths"]
    ok = paths["/healthz"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert ok == {"$ref": "#/components/schemas/HealthStatus"}
    assert "503" in paths["/readyz"]["get"]["responses"]
