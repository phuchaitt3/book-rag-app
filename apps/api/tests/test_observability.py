import json
import logging
import uuid

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from book_rag_api.config import Settings
from book_rag_api.main import create_app
from book_rag_api.observability import (
    JsonFormatter,
    bind_log_context,
    make_formatter,
    request_id_var,
)

UNREACHABLE_DB = "postgresql+asyncpg://x:x@127.0.0.1:1/x"


def _app() -> FastAPI:
    app = create_app(Settings(database_url=UNREACHABLE_DB))

    @app.get("/boom")
    async def boom() -> None:
        logging.getLogger("test").warning("about to fail")
        raise HTTPException(409, "nothing to see")

    return app


async def test_request_id_round_trip_and_generated() -> None:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        echoed = await c.get("/healthz", headers={"X-Request-ID": "abc-123"})
        generated = await c.get("/healthz")
        unsafe = await c.get("/healthz", headers={"X-Request-ID": "bad id"})
    assert echoed.headers["x-request-id"] == "abc-123"
    assert len(uuid.UUID(generated.headers["x-request-id"]).hex) == 32
    assert unsafe.headers["x-request-id"] != "bad id"


async def test_json_log_line_carries_request_id(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    caplog.handler.setFormatter(JsonFormatter())  # formats while the request is still bound
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        await c.get("/boom", headers={"X-Request-ID": "req-42"})
    lines = [json.loads(line) for line in caplog.text.splitlines() if line.startswith("{")]
    warning = next(line for line in lines if line["message"] == "about to fail")
    assert warning["request_id"] == "req-42"
    assert {"timestamp", "level", "logger", "message"} <= warning.keys()
    access = next(line for line in lines if line["logger"] == "book_rag_api.request")
    assert access["status"] == 409 and access["request_id"] == "req-42"


async def test_app_error_is_rfc_9457_problem() -> None:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        response = await c.get("/boom", headers={"X-Request-ID": "req-7"})
    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json() == {
        "type": "about:blank",
        "title": "Conflict",
        "status": 409,
        "detail": "nothing to see",
        "request_id": "req-7",
    }


def test_bound_ids_appear_and_are_released() -> None:
    record = logging.LogRecord("x", logging.INFO, "f", 1, "hi", None, None)
    with bind_log_context(book_id="b1", job_id="j1"):
        bound = json.loads(JsonFormatter().format(record))
    after = json.loads(JsonFormatter().format(record))
    assert bound["book_id"] == "b1" and bound["job_id"] == "j1"
    assert "book_id" not in after and request_id_var.get() is None


def test_log_format_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    assert not isinstance(make_formatter(), JsonFormatter)
    monkeypatch.setenv("LOG_FORMAT", "json")
    assert isinstance(make_formatter(), JsonFormatter)
    with pytest.raises(ValueError):
        make_formatter("xml")
