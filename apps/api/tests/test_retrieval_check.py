import importlib.util
import json
import os
import sys
import threading
import unicodedata
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "experiments" / "e2e" / "retrieval_check.py"
CITATIONS = 'event: citations\ndata: [{"chunk_id": "a"}, {"chunk_id": "b"}]\n\n'
TOKEN = 'event: token\ndata: {"text": "hi"}\n\n'


@pytest.fixture(scope="module")
def rc() -> Iterator[ModuleType]:
    previous = os.environ.get("BOOK_ID")
    os.environ["BOOK_ID"] = "00000000-0000-0000-0000-000000000000"
    spec = importlib.util.spec_from_file_location("retrieval_check_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)
    if previous is None:
        os.environ.pop("BOOK_ID", None)
    else:
        os.environ["BOOK_ID"] = previous


def test_norm_ignores_case(rc: ModuleType) -> None:
    assert rc.norm("Hello World") == rc.norm("hello world")


def test_norm_equates_composed_and_decomposed_vietnamese(rc: ModuleType) -> None:
    composed = unicodedata.normalize("NFC", "Tiếng Việt")
    decomposed = unicodedata.normalize("NFD", "Tiếng Việt")
    assert composed != decomposed
    assert rc.norm(composed) == rc.norm(decomposed)


def test_norm_ignores_hyphens_spaces_and_line_breaks(rc: ModuleType) -> None:
    assert (
        rc.norm("well-known\nfact  here") == rc.norm("well known fact here") == "wellknownfacthere"
    )


def test_interval_all_hits_is_one(rc: ModuleType) -> None:
    assert rc.interval([1] * 20) == (1.0, 1.0)


def test_interval_is_deterministic_and_ordered(rc: ModuleType) -> None:
    hits = [1, 0, 1, 1, 0, 0, 1, 0, 1, 1]
    first = rc.interval(hits, reps=500)
    assert first == rc.interval(hits, reps=500)
    low, high = first
    assert low <= sum(hits) / len(hits) <= high


def test_first_event_returns_both_chunk_ids(rc: ModuleType) -> None:
    assert rc.first_citations_event(CITATIONS.splitlines(keepends=True)) == ["a", "b"]


def test_first_event_stops_before_token_events(rc: ModuleType) -> None:
    def lines() -> Iterator[str]:
        yield from CITATIONS.splitlines(keepends=True)
        raise AssertionError("read past the citations event")

    assert rc.first_citations_event(lines()) == ["a", "b"]


def test_first_event_empty_or_missing_gives_empty_list(rc: ModuleType) -> None:
    assert rc.first_citations_event([]) == []
    assert rc.first_citations_event(["event: citations\n", "data: []\n", "\n"]) == []
    assert rc.first_citations_event(["event: citations\n", "\n"]) == []


def test_citations_reads_first_event_from_a_local_server(
    rc: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers["Content-Length"])
            seen["path"] = self.path
            seen["body"] = json.loads(self.rfile.read(length))
            payload = (CITATIONS + TOKEN).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setattr(rc, "API_URL", f"http://127.0.0.1:{server.server_port}")
        ids, elapsed = rc.citations("what?")
    finally:
        server.shutdown()
        server.server_close()
    assert ids == ["a", "b"]
    assert elapsed >= 0
    assert seen["path"] == f"/books/{rc.BOOK_ID}/chat"
    assert seen["body"] == {"question": "what?", "top_k": rc.TOP_K}
