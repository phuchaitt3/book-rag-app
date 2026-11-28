"""Concurrency benchmark of one OpenAI-compatible chat server (#245, pre-registered in
docs/benchmarks/vllm-concurrency.md).

Sends every prompt of a prompts file (`dump_prompts.py` output) to
`POST {BASE_URL}/v1/chat/completions` with `stream: true`, with C requests in flight at once
(a worker pool; each worker sends its next prompt when its previous one ends), for each C in
CONCURRENCY. The same script and the same prompts are used for every server (vLLM, Ollama's
OpenAI endpoint, llama.cpp), so the arms differ only in the server.

Per request: `t_first_token` (seconds from just before sending to the first non-empty content
delta), `t_total` (to `[DONE]`), `output_tokens` (the server's `usage.completion_tokens`, else the
number of content deltas), `decode_tps` (output_tokens / (t_total - t_first_token)). Per level also
`wall_s` and `aggregate_tps` (all output tokens / wall time) and the peak GPU memory that
`nvidia-smi` reported while the level ran (whole GPU, so it includes any memory the server
reserves up front; vLLM reserves `gpu_memory_utilization` of the card for its KV cache).

Environment: BASE_URL, MODEL, LABEL, PROMPTS (required), CONCURRENCY ("1,4,16"), MAX_TOKENS
(256), WARMUP (4), OUT_DIR, GPU_INDEX (0), SERVER_INFO (free text stored in the summary).
Standard library only, besides `measure.py` next to it (percentiles and bootstrap intervals).
"""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from measure import bootstrap_ci, percentile

HERE = Path(__file__).resolve().parent


def parse_stream(lines: Iterable[tuple[float, bytes]], start: float) -> dict[str, Any]:
    """Turn (timestamp, raw line) pairs of a chat-completions stream into one timing record."""
    rec: dict[str, Any] = {
        "t_first_token": None,
        "t_total": None,
        "output_tokens": 0,
        "error": False,
    }
    deltas = 0
    usage_tokens: int | None = None
    for ts, raw in lines:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line.startswith("data:"):
            continue
        data = line[len("data:") :].strip()
        if data == "[DONE]":
            rec["t_total"] = ts - start
            break
        event = json.loads(data)
        if event.get("usage") and event["usage"].get("completion_tokens") is not None:
            usage_tokens = int(event["usage"]["completion_tokens"])
        for choice in event.get("choices", []):
            if (choice.get("delta") or {}).get("content"):
                deltas += 1
                if rec["t_first_token"] is None:
                    rec["t_first_token"] = ts - start
    rec["output_tokens"] = usage_tokens if usage_tokens is not None else deltas
    if rec["t_total"] is None or rec["t_first_token"] is None:
        rec["error"] = True
    elif rec["t_total"] > rec["t_first_token"] and rec["output_tokens"] > 1:
        rec["decode_tps"] = (rec["output_tokens"] - 1) / (rec["t_total"] - rec["t_first_token"])
    return rec


def send(base_url: str, model: str, messages: list[dict], max_tokens: int) -> dict[str, Any]:
    body = {
        "model": model,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
        "max_tokens": max_tokens,
        "temperature": 0,
    }
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=900) as resp:
            return parse_stream(((time.perf_counter(), raw) for raw in resp), start)
    except Exception as exc:
        return {
            "t_first_token": None,
            "t_total": None,
            "output_tokens": 0,
            "error": True,
            "error_message": f"{type(exc).__name__}: {exc}",
        }


def stat(values: list[float]) -> dict[str, Any]:
    out: dict[str, Any] = {"n": len(values)}
    for name, p in (("p50", 50), ("p95", 95)):
        out[name] = percentile(values, p)
        out[f"{name}_ci95"] = bootstrap_ci(values, p, resamples=2_000)
    return out


def summarise_level(
    records: list[dict[str, Any]], wall_s: float, concurrency: int
) -> dict[str, Any]:
    ok = [r for r in records if not r["error"]]
    tokens = sum(r["output_tokens"] for r in ok)
    return {
        "concurrency": concurrency,
        "requests": len(records),
        "errors": len(records) - len(ok),
        "wall_s": wall_s,
        "output_tokens": tokens,
        "aggregate_tps": tokens / wall_s if wall_s else None,
        "t_first_token": stat([r["t_first_token"] for r in ok]),
        "t_total": stat([r["t_total"] for r in ok]),
        "decode_tps": stat([r["decode_tps"] for r in ok if "decode_tps" in r]),
    }


class VramWatcher:
    """Polls nvidia-smi for the used memory (MiB) of one GPU; `peak` after `stop()`."""

    def __init__(self, gpu_index: str, interval: float = 0.5) -> None:
        self.gpu_index, self.interval = gpu_index, interval
        self.peak: int | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _read(self) -> int | None:
        try:
            out = subprocess.run(
                [
                    "nvidia-smi",
                    "-i",
                    self.gpu_index,
                    "--query-gpu=memory.used",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            ).stdout
            return int(out.strip().splitlines()[0])
        except Exception:
            return None

    def _run(self) -> None:
        while not self._stop.is_set():
            used = self._read()
            if used is not None and (self.peak is None or used > self.peak):
                self.peak = used
            self._stop.wait(self.interval)

    def start(self) -> "VramWatcher":
        self._thread.start()
        return self

    def stop(self) -> int | None:
        self._stop.set()
        self._thread.join()
        return self.peak


def run_level(
    base_url: str,
    model: str,
    prompts: list[dict],
    concurrency: int,
    max_tokens: int,
    gpu_index: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    watcher = VramWatcher(gpu_index).start()
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        records = list(
            pool.map(lambda p: send(base_url, model, p["messages"], max_tokens), prompts)
        )
    wall = time.perf_counter() - t0
    peak = watcher.stop()
    summary = summarise_level(records, wall, concurrency)
    summary["peak_vram_mib"] = peak
    return records, summary


def main() -> None:
    env = os.environ
    base_url, model, label = env["BASE_URL"], env["MODEL"], env.get("LABEL", "run")
    prompts = [
        json.loads(x)
        for x in Path(env["PROMPTS"]).read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]
    levels = [int(x) for x in env.get("CONCURRENCY", "1,4,16").split(",")]
    max_tokens, warmup = int(env.get("MAX_TOKENS", "256")), int(env.get("WARMUP", "4"))
    gpu_index, out_dir = env.get("GPU_INDEX", "0"), Path(env.get("OUT_DIR", HERE / "results"))
    for p in prompts[:warmup]:  # not counted: loads the model and warms the kernels
        send(base_url, model, p["messages"], max_tokens)
    summaries, raw = [], []
    for c in levels:
        records, summary = run_level(base_url, model, prompts, c, max_tokens, gpu_index)
        summaries.append(summary)
        raw += [{"concurrency": c, **r} for r in records]
        print(
            json.dumps(
                {
                    k: summary[k]
                    for k in ("concurrency", "errors", "wall_s", "aggregate_tps", "peak_vram_mib")
                }
            ),
            flush=True,
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{label}.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in raw), encoding="utf-8"
    )
    (out_dir / f"{label}-summary.json").write_text(
        json.dumps(
            {
                "label": label,
                "model": model,
                "server": env.get("SERVER_INFO", ""),
                "prompts": len(prompts),
                "max_tokens": max_tokens,
                "warmup": warmup,
                "temperature": 0,
                "when": datetime.now(UTC).isoformat(timespec="seconds"),
                "levels": summaries,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
