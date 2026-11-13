"""Measure serving latency of the chat endpoint over SSE (issue #190).

Sends each question to POST {API_URL}/books/{BOOK_ID}/chat, one request at a time, and records
seconds since just before the request was sent (time.perf_counter):

- t_citations: first `citations` event (retrieval and reranking are done by then)
- t_first_token: first `token` event
- t_total: `done` event

The first WARMUP questions run but are not counted. Output goes to
OUT_DIR/<LABEL>.jsonl (one raw record per counted question) and OUT_DIR/<LABEL>-summary.json
(n, median and p90 of each timing, error count, and the measurement conditions).

Percentiles use the nearest-rank method: for n sorted values and percentile p, the value at
1-based rank ceil(p/100 * n). The median is the 50th percentile by the same method (the lower
middle value for even n). Records with an error or a missing timing are left out of that timing.

Environment: API_URL, BOOK_ID (required), LABEL, QUESTIONS, WARMUP, OUT_DIR, OLLAMA_URL,
LLM_MODEL, EMBEDDING_MODEL. Standard library only.
"""

import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
TIMINGS = ("t_citations", "t_first_token", "t_total")


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile (p in 0..100); None for an empty list."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(p / 100 * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def parse_sse_stream(lines: Iterable[tuple[float, str]], start: float) -> dict[str, Any]:
    """Turn (timestamp, line) pairs of an SSE stream into one timing record.

    Timestamps are perf_counter values; `start` is the value taken just before sending.
    An event counts when its `event:` line is seen, which is when the server flushed it.
    """
    rec: dict[str, Any] = {
        "t_citations": None,
        "t_first_token": None,
        "t_total": None,
        "token_events": 0,
        "error": False,
    }
    for ts, raw in lines:
        line = raw.rstrip("\r\n")
        if not line.startswith("event:"):
            continue
        name = line[len("event:") :].strip()
        if name == "citations" and rec["t_citations"] is None:
            rec["t_citations"] = ts - start
        elif name == "token":
            rec["token_events"] += 1
            if rec["t_first_token"] is None:
                rec["t_first_token"] = ts - start
        elif name == "done":
            rec["t_total"] = ts - start
        elif name == "error":
            rec["error"] = True
    if rec["t_total"] is None:
        rec["error"] = True
    return rec


def summarise(records: list[dict[str, Any]]) -> dict[str, Any]:
    """n, error count, and median and p90 of each timing over the records."""
    out: dict[str, Any] = {
        "n": len(records),
        "errors": sum(1 for r in records if r.get("error")),
    }
    for key in TIMINGS:
        vals = [r[key] for r in records if not r.get("error") and r.get(key) is not None]
        out[key] = {
            "n": len(vals),
            "median": percentile(vals, 50),
            "p90": percentile(vals, 90),
        }
    return out


def _lines_with_time(resp: Any) -> Iterable[tuple[float, str]]:
    for raw in resp:
        yield time.perf_counter(), raw.decode("utf-8", errors="replace")


def ask(api_url: str, book_id: str, question: str, timeout: float = 600) -> dict[str, Any]:
    body = json.dumps({"question": question, "top_k": 6}).encode()
    req = urllib.request.Request(
        f"{api_url.rstrip('/')}/books/{book_id}/chat",
        data=body,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return parse_sse_stream(_lines_with_time(resp), start)
    except Exception as exc:
        return {
            "t_citations": None,
            "t_first_token": None,
            "t_total": None,
            "token_events": 0,
            "error": True,
            "error_message": f"{type(exc).__name__}: {exc}",
        }


def _get_json(url: str, data: dict[str, Any] | None = None) -> Any:
    payload = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"} if payload else {}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)


def _model_info(ollama_url: str, name: str) -> dict[str, Any]:
    info: dict[str, Any] = {"name": name}
    try:
        for m in _get_json(f"{ollama_url}/api/tags").get("models", []):
            if m.get("name") in (name, f"{name}:latest"):
                info["digest"] = m.get("digest")
                info["size"] = m.get("size")
        shown = _get_json(f"{ollama_url}/api/show", {"model": name}).get("details", {})
        info["quantization"] = shown.get("quantization_level")
        info["parameter_size"] = shown.get("parameter_size")
    except Exception as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info


def _run(cmd: list[str]) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=True, cwd=REPO)
        return out.stdout.strip()
    except Exception:
        return None


def tei_image(compose: Path) -> str | None:
    try:
        m = re.search(r"^\s*image:\s*(\S+)", compose.read_text(encoding="utf-8"), re.MULTILINE)
    except OSError:
        return None
    return m.group(1) if m else None


def collect_conditions(label: str) -> dict[str, Any]:
    ollama_url = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
    ollama: dict[str, Any] = {}
    try:
        ollama["version"] = _get_json(f"{ollama_url}/api/version").get("version")
    except Exception as exc:
        ollama["version_error"] = f"{type(exc).__name__}: {exc}"
    llm = os.environ.get("LLM_MODEL", "qwen2.5:7b-instruct")
    emb = os.environ.get("EMBEDDING_MODEL", "bge-m3")
    ollama["chat_model"] = _model_info(ollama_url, llm)
    ollama["embedding_model"] = _model_info(ollama_url, emb)
    return {
        "label": label,
        "date_utc": datetime.now(UTC).strftime("%Y-%m-%d"),
        "git_commit": _run(["git", "rev-parse", "HEAD"]),
        "gpu": _run(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"]
        ),
        "ollama": ollama,
        "tei_image": tei_image(REPO / "compose.reranker.yaml"),
    }


def main() -> int:
    api_url = os.environ.get("API_URL", "http://localhost:8000")
    book_id = os.environ.get("BOOK_ID")
    if not book_id:
        print("BOOK_ID is required", file=sys.stderr)
        return 2
    label = os.environ.get("LABEL", "run")
    questions = json.loads(
        Path(os.environ.get("QUESTIONS", str(HERE / "questions.json"))).read_text(encoding="utf-8")
    )
    warmup = int(os.environ.get("WARMUP", "3"))
    out_dir = Path(os.environ.get("OUT_DIR", str(HERE / "results")))
    out_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    for i, q in enumerate(questions):
        rec = ask(api_url, book_id, q["question"])
        counted = i >= warmup
        status = "error" if rec["error"] else f"total {rec['t_total']:.2f}s"
        print(f"[{i + 1}/{len(questions)}] {'' if counted else 'warmup '}{q['id']}: {status}")
        if counted:
            records.append({"id": q["id"], **rec})

    with (out_dir / f"{label}.jsonl").open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    summary = {**summarise(records), "conditions": collect_conditions(label)}
    (out_dir / f"{label}-summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in summary.items() if k != "conditions"}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
