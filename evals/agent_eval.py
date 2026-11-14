"""Two-hop benchmark: a tool-using agent against single-shot chat (#243).

The committed test set has single-chunk questions only (the multi-chunk set, #183, does not
exist), so this builds a deterministic compound set from the blind questions: two questions whose
evidence sentences sit in different chunks of the ingested book are asked as one ("answer both").
A part is a hit when its evidence sentence is in a chunk the arm presented; a question is a hit
when both parts are (the matching rule of `experiments/e2e/retrieval_check.py`).

Arms, all on the same retriever (hybrid search, reranker off):

- single-shot: one `POST /books/{id}/chat` with the compound question, `top_k` 6; the chunks are
  the `citations` event, the answer is the streamed reply;
- agent: `book_agent.run_agent` over the MCP server (stdio subprocess), up to MAX_STEPS turns;
- control (retrieval only): one MCP `search_book` with the compound question and k = CONTROL_K,
  to see how much of the agent's gain is just more passages.

  BOOK_ID=<uuid> LABEL=run uv run python evals/agent_eval.py

Environment: BOOK_ID (required), API_URL, DATABASE_URL, QUESTIONS, LABEL, OUT_DIR, PAIRS (40),
SEED (243), MAX_STEPS (4), MODEL (qwen2.5:3b-instruct), MODE (native|json), OLLAMA_URL, TOP_K (6),
CONTROL_K (12), ARMS (single,agent,control), LIMIT (0 = all pairs).
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import statistics
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

sys.path.insert(0, str(Path(__file__).resolve().parent))
import answer_eval
import book_agent

ROOT = Path(__file__).resolve().parent.parent
norm = answer_eval.norm


def build_pairs(
    rows: Sequence[Mapping[str, Any]], chunks: Sequence[tuple[str, str]], n: int, seed: int
) -> list[tuple[Mapping[str, Any], Mapping[str, Any]]]:
    """`n` pairs of blind questions whose evidence sits in different chunks, deterministic in
    `seed`. `chunks` is (chunk_id, normalised text) in book order. A question whose evidence is
    not inside one chunk of this book is dropped (the PDF's chunking differs from the set's)."""
    located: list[tuple[Mapping[str, Any], int]] = []
    for row in rows:
        evidence = norm(row["evidence"])
        where = next((i for i, (_, text) in enumerate(chunks) if evidence in text), None)
        if where is not None:
            located.append((row, where))
    rng = random.Random(seed)
    rng.shuffle(located)
    pairs: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    pending: tuple[Mapping[str, Any], int] | None = None
    for row, where in located:
        if pending is None:
            pending = (row, where)
        elif pending[1] != where:
            pairs.append((pending[0], row))
            pending = None
            if len(pairs) == n:
                break
    return pairs


def compound(a: Mapping[str, Any], b: Mapping[str, Any]) -> str:
    return f"Hãy trả lời cả hai câu hỏi sau. (1) {a['question']} (2) {b['question']}"


def score(
    pair: tuple[Mapping[str, Any], Mapping[str, Any]],
    texts: Mapping[str, str],
    seen: Sequence[str],
    cited: Sequence[str],
    answer: str,
    marker_limit: int,
) -> dict[str, Any]:
    """Hits on the presented chunks and on the chunks the answer cites, and answer overlap."""
    ev = [norm(r["evidence"]) for r in pair]
    out: dict[str, Any] = {
        "seen": len(seen),
        "seen_hits": [any(e in texts.get(c, "") for c in seen) for e in ev],
        "cited_hits": [any(e in texts.get(c, "") for c in cited) for e in ev],
    }
    out["both_seen"] = all(out["seen_hits"])
    out["both_cited"] = all(out["cited_hits"])
    numbers = [int(m) for m in answer_eval.MARKER.findall(answer)]
    out["markers"] = len(numbers)
    out["marker_valid"] = all(1 <= x <= marker_limit for x in numbers)
    reference = f"{pair[0]['answer']} {pair[1]['answer']}"
    out["token_f1"], out["reference_recall"] = answer_eval.overlap(answer, reference)
    return out


def bootstrap(values: Sequence[float], seed: int, reps: int = 10_000) -> tuple[float, float]:
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(reps))
    return means[int(0.025 * reps)], means[int(0.975 * reps)]


def paired_diff(a: Sequence[float], b: Sequence[float], seed: int) -> tuple[float, float, float]:
    """Mean of a-b and its bootstrap 95% interval, resampling questions."""
    d = [x - y for x, y in zip(a, b, strict=True)]
    low, high = bootstrap(d, seed)
    return sum(d) / len(d), low, high


def summarise(results: Sequence[Mapping[str, Any]], seed: int) -> dict[str, Any]:
    def rate(key: str, values: Sequence[float]) -> dict[str, float]:
        low, high = bootstrap(values, seed)
        return {
            key: round(100 * sum(values) / len(values), 1),
            "ci95": [round(100 * low, 1), round(100 * high, 1)],
        }

    def interval_of(values: Sequence[float]) -> dict[str, Any] | None:
        if not values:
            return None
        low, high = bootstrap(values, seed)
        return {"mean": round(statistics.fmean(values), 2), "ci95": [round(low, 2), round(high, 2)]}

    parts_seen = [float(h) for r in results for h in r["seen_hits"]]
    parts_cited = [float(h) for r in results for h in r["cited_hits"]]
    return {
        "questions": len(results),
        "both_hit_seen": rate("pct", [float(r["both_seen"]) for r in results]),
        "part_hit_seen": rate("pct", parts_seen),
        "both_hit_cited": rate("pct", [float(r["both_cited"]) for r in results]),
        "part_hit_cited": rate("pct", parts_cited),
        "chunks_seen": interval_of([float(r["seen"]) for r in results]),
        "tool_calls": interval_of([float(r.get("tool_calls", 1)) for r in results]),
        "seconds": interval_of([float(r["seconds"]) for r in results]),
        "token_f1": interval_of([r["token_f1"] for r in results if "answer" in r]),
        "reference_recall": interval_of([r["reference_recall"] for r in results if "answer" in r]),
        "answers_without_marker_pct": round(
            100
            * sum(r["markers"] == 0 for r in results if "answer" in r)
            / max(1, sum("answer" in r for r in results)),
            1,
        ),
        "marker_invalid": sum(not r["marker_valid"] for r in results if "answer" in r),
        "errors": sum(bool(r.get("error")) for r in results),
        "capped": sum(bool(r.get("capped")) for r in results),
    }


async def single_shot(
    client: httpx.AsyncClient, book_id: str, question: str, top_k: int
) -> tuple[list[str], str, str | None]:
    response = await client.post(
        f"/books/{book_id}/chat", json={"question": question, "top_k": top_k}
    )
    if response.status_code != 200:
        return [], "", f"status {response.status_code}"
    events = answer_eval.parse_events(response.text)
    names = [name for name, _ in events]
    ids = [c["chunk_id"] for c in events[0][1]] if names[:1] == ["citations"] else []
    answer = "".join(d.get("text", "") for n, d in events if n == "token")
    return ids, answer, "stream error" if "error" in names else None


def write_results(out_dir: Path, label: str, payload: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"agent-eval-{label}.json").write_text(
        json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8"
    )


def git_commit() -> str:
    out = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT
    )
    return out.stdout.strip()


async def main() -> None:
    env = os.environ
    book_id = env["BOOK_ID"]
    label = env.get("LABEL", "run")
    seed = int(env.get("SEED", "243"))
    max_steps = int(env.get("MAX_STEPS", "4"))
    mode = env.get("MODE", "native")
    model_name = env.get("MODEL", "qwen2.5:3b-instruct")
    top_k = int(env.get("TOP_K", "6"))
    control_k = int(env.get("CONTROL_K", "12"))
    arms = env.get("ARMS", "single,agent,control").split(",")
    database_url = env.get("DATABASE_URL", "postgresql://bookrag:bookrag@localhost:5432/bookrag")
    ollama_url = env.get("OLLAMA_URL", "http://127.0.0.1:11434")
    out_dir = Path(env.get("OUT_DIR", ROOT / "experiments" / "agent" / "results"))

    import asyncpg  # type: ignore[import-untyped]

    conn = await asyncpg.connect(database_url)
    try:
        db_rows = await conn.fetch(
            "SELECT id, text FROM chunks WHERE book_id = $1::uuid ORDER BY ordinal", book_id
        )
    finally:
        await conn.close()
    chunks = [(str(r["id"]), norm(r["text"])) for r in db_rows]
    texts = dict(chunks)
    questions = answer_eval.load_questions(
        Path(env.get("QUESTIONS", ROOT / "experiments" / "book-testset" / "questions.jsonl")),
        ["blind"],
    )
    pairs = build_pairs(questions, chunks, int(env.get("PAIRS", "40")), seed)
    if limit := int(env.get("LIMIT", "0")):
        pairs = pairs[:limit]
    print(f"{len(pairs)} pairs from {len(questions)} blind questions", flush=True)

    model = book_agent.OllamaToolModel(model_name, mode=mode, base_url=ollama_url)
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "book_rag_api.mcp_server"],
        env={
            "DATABASE_URL": env.get(
                "MCP_DATABASE_URL", "postgresql+asyncpg://bookrag:bookrag@localhost:5432/bookrag"
            ),
            "OLLAMA_URL": ollama_url,
        },
        cwd=str(ROOT),
    )
    per_arm: dict[str, list[dict[str, Any]]] = {a: [] for a in arms}
    async with (
        Client(server) as mcp,
        httpx.AsyncClient(base_url=env.get("API_URL", "http://localhost:8000"), timeout=300) as api,
    ):
        backend = await book_agent.McpBackend.connect(mcp, book_id)
        await model.reply([{"role": "user", "content": "Xin chào"}], None)  # load the model
        await backend.call("search_book", {"query": "sử", "k": 1})  # warm the embedder
        for i, pair in enumerate(pairs):
            question = compound(*pair)
            base = {"pair": [pair[0]["id"], pair[1]["id"]]}
            if "single" in arms:
                start = time.perf_counter()
                ids, answer, error = await single_shot(api, book_id, question, top_k)
                seconds = time.perf_counter() - start
                cited = [
                    ids[x - 1]
                    for x in dict.fromkeys(int(m) for m in answer_eval.MARKER.findall(answer))
                    if 1 <= x <= len(ids)
                ]
                per_arm["single"].append(
                    {
                        **base,
                        **score(pair, texts, ids, cited, answer, len(ids)),
                        "answer": answer,
                        "seconds": seconds,
                        "error": error,
                        "tool_calls": 1,
                    }
                )
            if "agent" in arms:
                run = await book_agent.run_agent(
                    model, backend, question, max_steps=max_steps, mode=mode
                )
                per_arm["agent"].append(
                    {
                        **base,
                        **score(pair, texts, run.seen, run.cited, run.answer, len(run.seen)),
                        "answer": run.answer,
                        "seconds": run.seconds,
                        "error": run.error,
                        "tool_calls": len(run.tool_calls),
                        "steps": run.steps,
                        "capped": run.capped,
                        "model_calls": run.model_calls,
                        "queries": [c["arguments"] for c in run.tool_calls],
                        "citations": run.citations,
                    }
                )
            if "control" in arms:
                start = time.perf_counter()
                found = await backend.call("search_book", {"query": question, "k": control_k})
                seconds = time.perf_counter() - start
                ids = [p["chunk_id"] for p in found["passages"]]
                per_arm["control"].append(
                    {
                        **base,
                        **score(pair, texts, ids, [], "", 0),
                        "seconds": seconds,
                        "tool_calls": 1,
                    }
                )
            print(i + 1, {a: per_arm[a][-1]["both_seen"] for a in arms}, flush=True)

    summary: dict[str, Any] = {
        "label": label,
        "book_id": book_id,
        "commit": git_commit(),
        "model": model_name,
        "mode": mode,
        "max_steps": max_steps,
        "top_k": top_k,
        "control_k": control_k,
        "seed": seed,
        "pairs": len(pairs),
        "arms": {a: summarise(r, seed) for a, r in per_arm.items()},
    }
    if "single" in per_arm and "agent" in per_arm:
        for key in ("both_seen", "both_cited"):
            d = paired_diff(
                [float(r[key]) for r in per_arm["agent"]],
                [float(r[key]) for r in per_arm["single"]],
                seed,
            )
            summary[f"agent_minus_single_{key}_pts"] = [round(100 * v, 1) for v in d]
    write_results(out_dir, label, {"summary": summary, "results": per_arm})
    print(json.dumps(summary, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
