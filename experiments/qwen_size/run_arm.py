"""One arm of the 0.5B vs 3B answer-model comparison (#287): ask every question once, in order.

Each question of the book test set (kinds `blind` and `unanswerable`) goes to the running app's
`POST /books/{id}/chat`, one at a time. The reply is scored by `evals/answer_eval.py` (its
`score_stream` is imported, not copied). On top of that this script records the time from just
before the request to the first `token` event, the whole-answer time, the passages the answer
cites (for the judge), and the peak GPU memory used during the arm (nvidia-smi, every 0.5 s).

  BOOK_ID=<uuid> LABEL=0.5b MODEL=eval287-0.5b uv run python experiments/qwen_size/run_arm.py

Environment: BOOK_ID (required), LABEL (arm), MODEL (recorded only; the API's LLM_MODEL answers),
LIMIT (0 = all; n takes the first n blind and n//2+1 unanswerable questions, for a smoke run),
API_URL, DATABASE_URL, DEV_USER, TOP_K (6), OUT_DIR (experiments/qwen_size/results).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ae = load_module("answer_eval_for_qwen_size", ROOT / "evals" / "answer_eval.py")


def gpu_memory_mib() -> int | None:
    """Memory in use on the first GPU, all processes together; None when nvidia-smi fails."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout
        return int(out.strip().splitlines()[0])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


class VramSampler:
    """Polls GPU memory in a thread; `stop()` returns the reading before the start and the peak."""

    def __init__(self, interval: float = 0.5) -> None:
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self.baseline_mib = gpu_memory_mib()
        self.peak_mib = self.baseline_mib
        self.samples = 0

    def _run(self) -> None:
        while not self._stop.is_set():
            value = gpu_memory_mib()
            if value is not None:
                self.samples += 1
                self.peak_mib = value if self.peak_mib is None else max(self.peak_mib, value)
            self._stop.wait(self._interval)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> dict[str, int | None]:
        self._stop.set()
        self._thread.join(timeout=15)
        return {
            "baseline_mib": self.baseline_mib,
            "peak_mib": self.peak_mib,
            "samples": self.samples,
        }


def shown_passages(
    answer: str, cites: list[dict[str, Any]], raw: dict[str, str]
) -> list[dict[str, Any]]:
    """The passages the answer cites; the first two retrieved when it cites none (as #244)."""
    numbers = sorted({int(m) for m in ae.MARKER.findall(answer) if 1 <= int(m) <= len(cites)})
    picked = [cites[n - 1] for n in numbers] or cites[:2]
    return [
        {
            "number": c["number"],
            "chunk_id": c["chunk_id"],
            "section": c.get("section"),
            "page": c.get("page"),
            "text": raw.get(c["chunk_id"], ""),
        }
        for c in picked
    ]


async def ask(
    client: httpx.AsyncClient,
    book_id: str,
    row: dict[str, Any],
    texts: dict[str, str],
    raw: dict[str, str],
    top_k: int,
) -> dict[str, Any]:
    start = time.perf_counter()
    first: float | None = None
    status, buf = 0, ""
    try:
        async with client.stream(
            "POST", f"/books/{book_id}/chat", json={"question": row["question"], "top_k": top_k}
        ) as response:
            status = response.status_code
            async for piece in response.aiter_text():
                buf += piece
                if first is None and "event: token" in buf:
                    first = time.perf_counter() - start
        result = ae.score_stream(status, buf, row, texts)
    except httpx.HTTPError as exc:
        result = ae.score_stream(0, "", row, texts)
        result["format_error"] = f"transport: {type(exc).__name__}"
    result["total_s"] = round(time.perf_counter() - start, 3)
    result["ttft_s"] = None if first is None else round(first, 3)
    result["kind"] = row["kind"]
    result["question"] = row["question"]
    result["reference"] = row.get("answer")
    result["passages"] = []
    try:
        events = ae.parse_events(buf) if status == 200 else []
    except ValueError:
        events = []
    if events and events[0][0] == "citations" and isinstance(events[0][1], list):
        result["passages"] = shown_passages(result["answer"], events[0][1], raw)
    return result


async def fetch_texts(database_url: str, book_id: str) -> dict[str, str]:
    import asyncpg  # type: ignore[import-untyped]

    conn = await asyncpg.connect(database_url)
    try:
        rows = await conn.fetch("SELECT id, text FROM chunks WHERE book_id = $1::uuid", book_id)
    finally:
        await conn.close()
    return {str(r["id"]): r["text"] for r in rows}


def pick(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if not limit:
        return rows
    blind = [r for r in rows if r["kind"] == "blind"][:limit]
    unanswerable = [r for r in rows if r["kind"] == "unanswerable"][: limit // 2 + 1]
    return blind + unanswerable


def git_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=ROOT,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


async def main() -> None:
    env = os.environ
    book_id, label = env["BOOK_ID"], env["LABEL"]
    top_k = int(env.get("TOP_K", "6"))
    questions = ROOT / "experiments" / "book-testset" / "questions.jsonl"
    rows = pick(ae.load_questions(questions, ["blind", "unanswerable"]), int(env.get("LIMIT", "0")))
    database_url = env.get("DATABASE_URL", "postgresql://bookrag:bookrag@localhost:5432/bookrag")
    raw = await fetch_texts(database_url, book_id)
    texts = {cid: ae.norm(t) for cid, t in raw.items()}
    sampler = VramSampler()
    sampler.start()
    started = time.strftime("%Y-%m-%d %H:%M:%S")
    results: list[dict[str, Any]] = []
    async with httpx.AsyncClient(
        base_url=env.get("API_URL", "http://localhost:8000"),
        timeout=300,
        headers={"X-Dev-User": env.get("DEV_USER", "dev-user")},
    ) as client:
        for i, row in enumerate(rows, 1):
            results.append(await ask(client, book_id, row, texts, raw, top_k))
            if i % 20 == 0 or i == len(rows):
                print(f"{label}: {i}/{len(rows)}", flush=True)
    vram = sampler.stop()
    meta = {
        "label": label,
        "model": env.get("MODEL", ""),
        "book_id": book_id,
        "top_k": top_k,
        "questions": len(rows),
        "commit": git_head(),
        "started": started,
        "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
        "vram": vram,
        "format_errors": sum(r["format_error"] is not None for r in results),
        "stream_errors": sum(bool(r["stream_error"]) for r in results),
    }
    out = Path(env.get("OUT_DIR", HERE / "results"))
    out.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
    (out / f"{label}.json").write_text(
        json.dumps({"meta": meta, "results": results}, indent=1, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
