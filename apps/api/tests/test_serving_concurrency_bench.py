import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import ModuleType

SERVING = Path(__file__).resolve().parents[3] / "experiments" / "serving"


def _load(name: str) -> ModuleType:
    sys.path.insert(0, str(SERVING))
    spec = importlib.util.spec_from_file_location(f"serving_{name}", SERVING / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bench = _load("concurrency_bench")
stub = _load("capture_stub")


def _line(obj: dict | str) -> bytes:
    return f"data: {obj if isinstance(obj, str) else json.dumps(obj)}\n\n".encode()


def _delta(text: str) -> dict:
    return {"choices": [{"delta": {"content": text}}]}


def test_parse_stream_uses_usage_tokens_and_times() -> None:
    lines = [
        (0.5, _line({"choices": [{"delta": {"role": "assistant"}}]})),
        (1.0, _line(_delta("a"))),
        (2.0, _line(_delta("b"))),
        (3.0, _line({"choices": [], "usage": {"completion_tokens": 5}})),
        (3.1, _line("[DONE]")),
    ]
    rec = bench.parse_stream(lines, 0.0)
    assert rec["t_first_token"] == 1.0
    assert rec["t_total"] == 3.1
    assert rec["output_tokens"] == 5
    assert not rec["error"]
    assert abs(rec["decode_tps"] - 4 / 2.1) < 1e-9


def test_parse_stream_counts_deltas_without_usage_and_flags_truncation() -> None:
    ok = bench.parse_stream(
        [(1.0, _line(_delta("a"))), (2.0, _line(_delta("b"))), (2.5, _line("[DONE]"))], 0.0
    )
    assert ok["output_tokens"] == 2
    cut = bench.parse_stream([(1.0, _line(_delta("a")))], 0.0)
    assert cut["error"]


def test_summarise_level_aggregates_and_drops_errors() -> None:
    records = [
        {
            "t_first_token": 0.1,
            "t_total": 1.0,
            "output_tokens": 10,
            "error": False,
            "decode_tps": 10.0,
        },
        {
            "t_first_token": 0.2,
            "t_total": 2.0,
            "output_tokens": 30,
            "error": False,
            "decode_tps": 15.0,
        },
        {"t_first_token": None, "t_total": None, "output_tokens": 0, "error": True},
    ]
    s = bench.summarise_level(records, wall_s=4.0, concurrency=2)
    assert (s["requests"], s["errors"], s["output_tokens"]) == (3, 1, 40)
    assert s["aggregate_tps"] == 10.0
    assert s["t_total"]["n"] == 2 and s["t_total"]["p50"] == 1.0


def test_send_against_stub_server_end_to_end(tmp_path: Path) -> None:
    out = tmp_path / "captured.jsonl"
    server = HTTPServer(("127.0.0.1", 0), stub.make_handler(out))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        messages = [{"role": "user", "content": "hi"}]
        rec = bench.send(f"http://127.0.0.1:{server.server_port}", "m", messages, 8)
    finally:
        server.shutdown()
    assert not rec["error"] and rec["output_tokens"] == 1
    assert json.loads(out.read_text().splitlines()[0])["messages"] == messages


class _Silent(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        self.send_response(500)
        self.end_headers()

    def log_message(self, *args: object) -> None:
        pass


def test_send_records_http_error() -> None:
    server = HTTPServer(("127.0.0.1", 0), _Silent)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        rec = bench.send(f"http://127.0.0.1:{server.server_port}", "m", [], 8)
    finally:
        server.shutdown()
    assert rec["error"] and "HTTPError" in rec["error_message"]
