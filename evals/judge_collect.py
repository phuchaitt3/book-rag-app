"""Collect real answers from the app's chat path for the judge and the labelling sheet (#244).

Questions come from the book test set (`experiments/book-testset/questions.jsonl`); each goes to
`POST /books/{id}/chat` of the running app on the ingested book. Two systems answer, so the pool
has good, partial and wrong answers and abstentions:

- `topk6`: the app's default (`top_k` 6);
- `topk1`: the same app with one passage (`top_k` 1), which often has too little to answer from.

A question is used once in the pool (never by both systems). The unanswerable questions (kind
`unanswerable`) are asked too: the right reply is the app's "not found" text. The rows are shuffled
and given neutral ids (`r001`, ...); the system stays in the collection file and in the key file of
`judge_sheet.py`, never in the sheet or in the judge's prompt.

Each row keeps the passages the answer cites with `[n]` markers (the first two retrieved when the
answer cites none), with their raw text from the database. The reference answer is the test set's;
for an unanswerable question it says the book has no answer.

  BOOK_ID=<uuid> uv run python evals/judge_collect.py

Environment: API_URL (http://localhost:8000), DATABASE_URL (postgresql://bookrag:bookrag@localhost:5432/bookrag),
ANSWER_MODEL (qwen2.5:3b-instruct, recorded as is; the API's LLM_MODEL decides what answers),
SEED (244), OUT (experiments/judge/collection.json), MIN_GAP_S (2.1, the
chat endpoint allows 30 questions a minute per client).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import random
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
NO_ANSWER = "Sách không có câu trả lời cho câu hỏi này (câu hỏi ngoài phạm vi sách)."

# (system, top_k, kind of question, how many): 100 answers in all, 40 of them go on the sheet.
PLAN: Sequence[tuple[str, int, str, int]] = (
    ("topk6", 6, "answerable", 45),
    ("topk6", 6, "unanswerable", 15),
    ("topk1", 1, "answerable", 30),
    ("topk1", 1, "unanswerable", 10),
)


def _answer_eval() -> ModuleType:
    spec = importlib.util.spec_from_file_location("answer_eval_for_judge", HERE / "answer_eval.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def pick_questions(
    rows: Sequence[Mapping[str, Any]], plan: Sequence[tuple[str, int, str, int]], seed: int
) -> list[tuple[str, int, Mapping[str, Any]]]:
    """(system, top_k, question) per plan cell, no question twice. Answerable ones are blind."""
    rng = random.Random(seed)
    pools = {
        "answerable": [r for r in rows if r["kind"] == "blind"],
        "unanswerable": [r for r in rows if r["kind"] == "unanswerable"],
    }
    for pool in pools.values():
        rng.shuffle(pool)
    chosen: list[tuple[str, int, Mapping[str, Any]]] = []
    for system, top_k, kind, count in plan:
        taken, pools[kind] = pools[kind][:count], pools[kind][count:]
        if len(taken) < count:
            raise ValueError(f"only {len(taken)} {kind} questions left for {system}")
        chosen += [(system, top_k, q) for q in taken]
    return chosen


def shown_passages(
    answer: str, citations: Sequence[Mapping[str, Any]], texts: Mapping[str, str], marker: Any
) -> list[dict[str, Any]]:
    """The passages the answer cites; the first two retrieved when it cites none."""
    numbers = sorted({int(m) for m in marker.findall(answer) if 1 <= int(m) <= len(citations)})
    picked = [citations[n - 1] for n in numbers] or list(citations[:2])
    return [
        {
            "number": c["number"],
            "chunk_id": c["chunk_id"],
            "section": c.get("section"),
            "page": c.get("page"),
            "text": texts.get(c["chunk_id"], ""),
        }
        for c in picked
    ]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")


async def chunk_texts(database_url: str, book_id: str) -> dict[str, str]:
    import asyncpg  # type: ignore[import-untyped]

    conn = await asyncpg.connect(database_url)
    try:
        rows = await conn.fetch("SELECT id, text FROM chunks WHERE book_id = $1::uuid", book_id)
    finally:
        await conn.close()
    return {str(r["id"]): r["text"] for r in rows}


async def ask(
    client: httpx.AsyncClient, book_id: str, question: str, top_k: int
) -> tuple[str, list[dict[str, Any]], bool] | None:
    """(answer, citations, abstained), or None when the reply is unusable (no answer to judge)."""
    ae = _answer_eval()
    for _ in range(5):
        response = await client.post(
            f"/books/{book_id}/chat", json={"question": question, "top_k": top_k}
        )
        if response.status_code == 429:
            await asyncio.sleep(10)
            continue
        if response.status_code != 200:
            return None
        try:
            events = ae.parse_events(response.text)
        except ValueError:
            return None
        names = [n for n, _ in events]
        if "error" in names or names[:1] != ["citations"] or names[-1:] != ["done"]:
            return None
        answer = "".join(d.get("text", "") for n, d in events if n == "token")
        done = events[-1][1]
        return answer, events[0][1], bool(isinstance(done, dict) and done.get("abstained"))
    return None


async def main() -> None:
    env = os.environ
    book_id = env["BOOK_ID"]
    ae = _answer_eval()
    questions = ae.load_questions(
        ROOT / "experiments" / "book-testset" / "questions.jsonl",
        ["blind", "unanswerable"],
    )
    chosen = pick_questions(questions, PLAN, int(env.get("SEED", "244")))
    texts = await chunk_texts(
        env.get("DATABASE_URL", "postgresql://bookrag:bookrag@localhost:5432/bookrag"), book_id
    )
    gap = float(env.get("MIN_GAP_S", "2.1"))
    collected: list[dict[str, Any]] = []
    skipped: list[str] = []
    async with httpx.AsyncClient(
        base_url=env.get("API_URL", "http://localhost:8000"), timeout=300
    ) as client:
        for system, top_k, q in chosen:
            start = time.perf_counter()
            got = await ask(client, book_id, q["question"], top_k)
            if got is None:
                skipped.append(q["id"])
            else:
                answer, citations, abstained = got
                collected.append(
                    {
                        "qid": q["id"],
                        "kind": q["kind"],
                        "system": system,
                        "top_k": top_k,
                        "question": q["question"],
                        "reference": q.get("answer") or NO_ANSWER,
                        "answer": answer,
                        "abstained": abstained,
                        "retrieved": len(citations),
                        "passages": shown_passages(answer, citations, texts, ae.MARKER),
                    }
                )
            await asyncio.sleep(max(0.0, gap - (time.perf_counter() - start)))
    random.Random(int(env.get("SEED", "244"))).shuffle(collected)
    for i, row in enumerate(collected, 1):
        row["row_id"] = f"r{i:03d}"
    out = Path(env.get("OUT", ROOT / "experiments" / "judge" / "collection.json"))
    payload = {
        "answer_model": env.get("ANSWER_MODEL", "qwen2.5:3b-instruct"),
        "book_id": book_id,
        "seed": int(env.get("SEED", "244")),
        "skipped_questions": skipped,
        "rows": collected,
    }
    write_json(out, payload)
    print(f"{len(collected)} answers collected, {len(skipped)} skipped, written to {out}")


if __name__ == "__main__":
    asyncio.run(main())
