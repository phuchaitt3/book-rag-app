"""Score the running app's retrieval on the book test set, through its own chat endpoint (#189).

For each question it POSTs to /books/{id}/chat, reads the first SSE event (`citations`, the
ranked chunks the answer would cite) and closes the stream, so no answer is generated. A hit
means a cited chunk's text contains the question's evidence sentence (the test set's gold
chunks are for the HTML chunking, not for this PDF's, so the evidence sentence is the match).
Chunk text is read from Postgres by chunk id. Run it once per reranker setting; RERANKER
decides only the label written to the results (set RERANKER_PROVIDER on the api container).

  BOOK_ID=<uuid> LABEL=rerank uv run python experiments/e2e/retrieval_check.py

Environment: API_URL (http://localhost:8000), DATABASE_URL (postgresql://bookrag:bookrag@localhost:5432/bookrag),
QUESTIONS (the committed set), KIND (blind), TOP_K (6), OUT_DIR (experiments/e2e/results).
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import statistics
import time
import unicodedata
import urllib.request
from pathlib import Path

import asyncpg  # type: ignore[import-untyped]

HERE = Path(__file__).parent
API_URL = os.environ.get("API_URL", "http://localhost:8000")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://bookrag:bookrag@localhost:5432/bookrag")
QUESTIONS = Path(os.environ.get("QUESTIONS", HERE.parent / "book-testset" / "questions.jsonl"))
KIND = os.environ.get("KIND", "blind")
TOP_K = int(os.environ.get("TOP_K", "6"))
BOOK_ID = os.environ["BOOK_ID"]
LABEL = os.environ.get("LABEL", "run")
OUT_DIR = Path(os.environ.get("OUT_DIR", HERE / "results"))
LIMIT = int(os.environ.get("LIMIT", "0"))
_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)


def norm(text: str) -> str:
    """Lowercase, NFC, letters and digits only (hyphens, spacing and line breaks are ignored)."""
    return _NON_WORD.sub("", unicodedata.normalize("NFC", text).lower())


def citations(question: str) -> tuple[list[str], float]:
    body = json.dumps({"question": question, "top_k": TOP_K}).encode()
    request = urllib.request.Request(
        f"{API_URL}/books/{BOOK_ID}/chat",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    start = time.perf_counter()
    with urllib.request.urlopen(request, timeout=120) as response:
        event = data = None
        for raw in response:
            line = raw.decode().rstrip("\n")
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data = line[5:].strip()
            elif not line and event == "citations":
                break
        elapsed = time.perf_counter() - start
    return [c["chunk_id"] for c in json.loads(data or "[]")], elapsed


def interval(hits: list[int], seed: int = 189, reps: int = 10_000) -> tuple[float, float]:
    rng = random.Random(seed)
    n = len(hits)
    means = sorted(sum(hits[rng.randrange(n)] for _ in range(n)) / n for _ in range(reps))
    return means[int(0.025 * reps)], means[int(0.975 * reps)]


def load_questions() -> list[dict[str, object]]:
    lines = QUESTIONS.read_text(encoding="utf-8").splitlines()
    rows = [json.loads(x) for x in lines if x]
    rows = [r for r in rows if r["kind"] == KIND]
    return rows[:LIMIT] if LIMIT else rows


def write_results(payload: dict[str, object]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"retrieval-{LABEL}.json").write_text(
        json.dumps(payload, indent=1), encoding="utf-8"
    )


async def main() -> None:
    rows = load_questions()
    conn = await asyncpg.connect(DATABASE_URL)
    texts = {
        str(r["id"]): norm(r["text"])
        for r in await conn.fetch("SELECT id, text FROM chunks WHERE book_id = $1::uuid", BOOK_ID)
    }
    await conn.close()
    whole = "".join(texts.values())
    results, skipped = [], []
    for row in rows:
        evidence = norm(row["evidence"])
        if evidence not in whole:
            # The evidence sentence spans a chunk boundary or differs in this PDF's text.
            skipped.append(row["id"])
            continue
        ids, elapsed = await asyncio.to_thread(citations, row["question"])
        rank = next((i + 1 for i, cid in enumerate(ids) if evidence in texts.get(cid, "")), None)
        results.append({"id": row["id"], "rank": rank, "retrieval_s": round(elapsed, 3)})
    summary: dict[str, object] = {
        "label": LABEL,
        "book_id": BOOK_ID,
        "kind": KIND,
        "top_k": TOP_K,
        "questions": len(rows),
        "scored": len(results),
        "skipped_evidence_not_in_one_chunk": len(skipped),
        "retrieval_s_median": round(statistics.median(r["retrieval_s"] for r in results), 3),
    }
    for k in (1, 5):
        hits = [int(r["rank"] is not None and r["rank"] <= k) for r in results]
        low, high = interval(hits)
        summary[f"hit@{k}"] = round(100 * sum(hits) / len(hits), 1)
        summary[f"hit@{k}_ci95"] = [round(100 * low, 1), round(100 * high, 1)]
    write_results({"summary": summary, "skipped": skipped, "results": results})
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
