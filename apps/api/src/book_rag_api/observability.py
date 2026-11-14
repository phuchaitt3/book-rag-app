"""Structured logs, request IDs and RFC 9457 error bodies (#224).

The API and the worker call `configure_logging`. `LOG_FORMAT=json` writes one JSON object per
line (stdlib only); `text` (the default) keeps the plain local format. `request_id`, `book_id`
and `job_id` live in context variables, so every log line written while they are bound carries
them without the call site passing them along.
"""

import contextvars
import json
import logging
import os
import re
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
PROBLEM_MEDIA_TYPE = "application/problem+json"

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)
book_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("book_id", default=None)
job_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("job_id", default=None)

_CONTEXT_FIELDS = (("request_id", request_id_var), ("book_id", book_id_var), ("job_id", job_id_var))
# Extra fields a call site may pass with `extra={...}`.
_EXTRA_FIELDS = ("method", "path", "status", "duration_ms")
# An inbound ID is echoed into headers and logs, so only a short, plain one is accepted.
_VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")
_TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


class JsonFormatter(logging.Formatter):
    """One JSON object per record: timestamp, level, logger, message, bound IDs, exception."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for name, var in _CONTEXT_FIELDS:
            value = var.get()
            if value is not None:
                entry[name] = value
        for name in _EXTRA_FIELDS:
            if hasattr(record, name):
                entry[name] = getattr(record, name)
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def make_formatter(log_format: str | None = None) -> logging.Formatter:
    """The formatter for `log_format`, default the `LOG_FORMAT` variable ("text" if unset)."""
    chosen = (log_format or os.environ.get("LOG_FORMAT") or "text").lower()
    if chosen == "json":
        return JsonFormatter()
    if chosen == "text":
        return logging.Formatter(_TEXT_FORMAT)
    raise ValueError(f"LOG_FORMAT must be 'json' or 'text', not {chosen!r}")


def configure_logging(log_format: str | None = None, level: int = logging.INFO) -> None:
    """Install the root handler with the chosen format."""
    handler = logging.StreamHandler()
    handler.setFormatter(make_formatter(log_format))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)


@contextmanager
def bind_log_context(*, book_id: object = None, job_id: object = None) -> Iterator[None]:
    """Bind `book_id` and/or `job_id` to every log line written inside the block."""
    tokens = []
    if book_id is not None:
        tokens.append((book_id_var, book_id_var.set(str(book_id))))
    if job_id is not None:
        tokens.append((job_id_var, job_id_var.set(str(job_id))))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


request_log = logging.getLogger("book_rag_api.request")


class RequestIdMiddleware:
    """Accepts `X-Request-ID` or makes one, binds it, echoes it, and logs each request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        supplied = dict(scope["headers"]).get(b"x-request-id", b"").decode("latin-1")
        request_id = supplied if _VALID_REQUEST_ID.fullmatch(supplied) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = [h for h in message["headers"] if h[0].lower() != b"x-request-id"]
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            request_log.info(
                "%s %s -> %s",
                scope["method"],
                scope["path"],
                status,
                extra={
                    "method": scope["method"],
                    "path": scope["path"],
                    "status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            request_id_var.reset(token)


def problem_response(
    status_code: int, detail: str, *, headers: dict[str, str] | None = None
) -> JSONResponse:
    """An RFC 9457 problem document. `type` is `about:blank`, so `title` is the status phrase."""
    body = {
        "type": "about:blank",
        "title": HTTPStatus(status_code).phrase,
        "status": status_code,
        "detail": detail,
        "request_id": request_id_var.get(),
    }
    return JSONResponse(
        body, status_code=status_code, headers=headers, media_type=PROBLEM_MEDIA_TYPE
    )


def install_problem_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_problem(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail)
        return problem_response(exc.status_code, detail, headers=dict(exc.headers or {}))
