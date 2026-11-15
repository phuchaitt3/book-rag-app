"""OpenAICompatLLM against a stub OpenAI-compatible server on a local port (#245)."""

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from book_rag.providers import LLM, Message, OpenAICompatLLM

EVENTS = [
    {"choices": [{"delta": {"role": "assistant"}}]},
    {"choices": [{"delta": {"content": "Xin"}}]},
    {"choices": [{"delta": {"content": " chào"}}]},
    {"choices": [{"delta": {}, "finish_reason": "stop"}]},
]


class Stub(HTTPServer):
    seen: list[dict[str, Any]]


class Handler(BaseHTTPRequestHandler):
    server: Stub

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.seen.append(
            {"path": self.path, "auth": self.headers.get("Authorization"), "body": body}
        )
        if self.path != "/v1/chat/completions":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for event in EVENTS:
            self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.write(b'data: {"choices": [{"delta": {"content": "NEVER"}}]}\n\n')

    def log_message(self, format: str, *args: Any) -> None:
        pass


@pytest.fixture
def stub() -> Iterator[Stub]:
    server = Stub(("127.0.0.1", 0), Handler)
    server.seen = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join()


async def test_streams_pieces_and_stops_at_done(stub: Stub) -> None:
    llm = OpenAICompatLLM("qwen", f"http://127.0.0.1:{stub.server_port}/", api_key="k")
    assert isinstance(llm, LLM)
    out = [p async for p in llm.stream([Message("system", "s"), Message("user", "hi")])]
    assert out == ["Xin", " chào"]
    request = stub.seen[0]
    assert request["path"] == "/v1/chat/completions"
    assert request["auth"] == "Bearer k"
    assert request["body"]["model"] == "qwen"
    assert request["body"]["stream"] is True
    assert request["body"]["messages"] == [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "hi"},
    ]


async def test_no_authorization_header_without_a_key(stub: Stub) -> None:
    llm = OpenAICompatLLM("qwen", f"http://127.0.0.1:{stub.server_port}")
    [p async for p in llm.stream([Message("user", "hi")])]
    assert stub.seen[0]["auth"] is None
