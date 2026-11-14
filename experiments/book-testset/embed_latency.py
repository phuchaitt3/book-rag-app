"""Where do the ~2.2 s of one Ollama query embedding go? (#185)

Times warm `/api/embed` calls for one short question, in arms that separate the client from
the runner: the app's `OllamaEmbedder` against `localhost` and against `127.0.0.1`, a raw
`http.client` call, Ollama's own `total_duration`/`load_duration` from the reply, a batch of
8 questions, and `keep_alive` set explicitly. Needs Ollama with bge-m3. From the repo root:
  uv run python experiments/book-testset/embed_latency.py
Environment: OLLAMA_MODEL (default bge-m3), N (calls per arm, default 8), TAGS (comma list of
extra model tags to time, for example a quantised bge-m3 if one is pulled).
"""

from __future__ import annotations

import asyncio
import http.client
import json
import os
import statistics
import time
from collections.abc import Callable
from typing import Any

from book_rag.providers import OllamaEmbedder

MODEL = os.environ.get("OLLAMA_MODEL", "bge-m3")
N = int(os.environ.get("N", "8"))
TAGS = [t for t in os.environ.get("TAGS", "").split(",") if t]
QUESTION = "Ai là người lãnh đạo cuộc khởi nghĩa Lam Sơn?"
BATCH = [QUESTION + f" ({i})" for i in range(8)]


def raw_embed(
    host: str, model: str, texts: list[str], extra: dict[str, str] | None = None
) -> dict[str, Any]:
    conn = http.client.HTTPConnection(host, 11434, timeout=300)
    body = json.dumps({"model": model, "input": texts, **(extra or {})})
    conn.request("POST", "/api/embed", body, {"Content-Type": "application/json"})
    reply = json.loads(conn.getresponse().read())
    conn.close()
    return reply


def report(name: str, ms: list[float], note: str = "") -> None:
    med = statistics.median(ms)
    print(f"{name:52s} median {med:7.0f} ms  min {min(ms):7.0f}  max {max(ms):7.0f}  {note}")


def timed(fn: Callable[[], object], n: int = N) -> list[float]:
    fn()  # warm-up, not counted
    out = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        out.append((time.perf_counter() - t) * 1000)
    return out


def one_model(model: str) -> None:
    print(f"--- model {model}")
    for host in ("localhost", "127.0.0.1"):
        emb = OllamaEmbedder(model, 1024, base_url=f"http://{host}:11434")
        ms = timed(lambda e=emb: asyncio.run(e.embed([QUESTION])))
        report(f"OllamaEmbedder.embed(1) via {host}", ms)
    for host in ("localhost", "127.0.0.1"):
        ms = timed(lambda h=host: raw_embed(h, model, [QUESTION]))
        report(f"http.client /api/embed(1) via {host}", ms)
    emb = OllamaEmbedder(model, 1024, base_url="http://127.0.0.1:11434")
    report("OllamaEmbedder.embed(8) via 127.0.0.1", timed(lambda: asyncio.run(emb.embed(BATCH))))
    keep = {"keep_alive": "30m"}
    ms = timed(lambda: raw_embed("127.0.0.1", model, [QUESTION], keep))
    report("http.client embed(1), keep_alive=30m", ms)
    reply = raw_embed("127.0.0.1", model, [QUESTION])
    print(
        "Ollama's own timing (ms): total",
        round(reply.get("total_duration", 0) / 1e6),
        "load",
        round(reply.get("load_duration", 0) / 1e6),
        "prompt_eval_count",
        reply.get("prompt_eval_count"),
    )


def main() -> None:
    for model in [MODEL, *TAGS]:
        one_model(model)


if __name__ == "__main__":
    main()
