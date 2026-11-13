import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import ModuleType

import pytest

PATH = Path(__file__).resolve().parents[3] / "experiments" / "serving" / "measure.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("serving_measure", PATH)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


measure = _load()


def test_percentile_nearest_rank() -> None:
    vals = [5.0, 1.0, 3.0, 2.0, 4.0]
    assert measure.percentile(vals, 50) == 3.0
    assert measure.percentile(vals, 90) == 5.0
    assert measure.percentile(vals, 20) == 1.0
    assert measure.percentile([float(i) for i in range(1, 11)], 90) == 9.0
    assert measure.percentile([], 50) is None


def test_parse_sse_stream_timings() -> None:
    lines = [
        (10.5, "event: citations\n"),
        (10.5, "data: []\n"),
        (10.5, "\n"),
        (11.0, "event: token\n"),
        (11.0, 'data: {"text": "a"}\n'),
        (12.0, "event: token\n"),
        (13.0, "event: done\n"),
    ]
    rec = measure.parse_sse_stream(lines, start=10.0)
    assert rec["t_citations"] == pytest.approx(0.5)
    assert rec["t_first_token"] == pytest.approx(1.0)
    assert rec["t_total"] == pytest.approx(3.0)
    assert rec["token_events"] == 2
    assert rec["error"] is False


def test_parse_sse_stream_error_and_truncated() -> None:
    rec = measure.parse_sse_stream([(1.0, "event: citations\n"), (2.0, "event: error\n")], 0.0)
    assert rec["error"] is True
    assert rec["t_total"] is None
    assert measure.parse_sse_stream([], 0.0)["error"] is True


def test_summarise() -> None:
    recs = [
        {"t_citations": 1.0, "t_first_token": 2.0, "t_total": 4.0, "error": False},
        {"t_citations": 2.0, "t_first_token": 3.0, "t_total": 5.0, "error": False},
        {"t_citations": 3.0, "t_first_token": 4.0, "t_total": 9.0, "error": False},
        {"t_citations": None, "t_first_token": None, "t_total": None, "error": True},
    ]
    s = measure.summarise(recs)
    assert s["n"] == 4
    assert s["errors"] == 1
    assert s["t_citations"] == {"n": 3, "median": 2.0, "p90": 3.0}
    assert s["t_total"]["median"] == 5.0


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        body = json.loads(self.rfile.read(length))
        assert body["top_k"] == 6
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for ev in ("citations", "token", "token", "done"):
            self.wfile.write(f"event: {ev}\ndata: {{}}\n\n".encode())
            self.wfile.flush()

    def log_message(self, format: str, *args: object) -> None:
        pass


def test_ask_against_fake_server() -> None:
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        rec = measure.ask(f"http://127.0.0.1:{server.server_port}", "book-1", "question?", 10)
    finally:
        server.shutdown()
        server.server_close()
    assert rec["error"] is False
    assert rec["token_events"] == 2
    assert 0 <= rec["t_citations"] <= rec["t_first_token"] <= rec["t_total"]
