"""Collect the best passage's score for each book test-set question, through the running app (#222).

Same method as retrieval_check.py: POST /books/{id}/chat, read the first SSE event (`citations`)
and close the stream, so no answer is generated. Each citation now carries the passage's
`score` (the reranker's, or the fused RRF score when no reranker ran). Run the API with the
abstain thresholds off (the default before the measured values are set, or ABSTAIN_BELOW_*
unset), otherwise an abstaining reply has no citations to read.

  BOOK_ID=<uuid> LABEL=rerank uv run python experiments/e2e/abstain_scores.py

Environment: API_URL (http://localhost:8000), QUESTIONS (the committed set), TOP_K (6),
OUT_DIR (experiments/e2e/results), LIMIT (0 = all). Writes abstain-scores-<LABEL>.json.
Rows: seen and blind questions (answerable) and the unanswerable ones, each with its `split`
(seen or blind; the unanswerable ones carry it in the file) and the top score.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
API_URL = os.environ.get("API_URL", "http://localhost:8000")
QUESTIONS = Path(os.environ.get("QUESTIONS", HERE.parent / "book-testset" / "questions.jsonl"))
BOOK_ID = os.environ["BOOK_ID"]
LABEL = os.environ.get("LABEL", "run")
TOP_K = int(os.environ.get("TOP_K", "6"))
OUT_DIR = Path(os.environ.get("OUT_DIR", HERE / "results"))
LIMIT = int(os.environ.get("LIMIT", "0"))


def first_citations(lines: list[str]) -> list[dict[str, object]]:
    event = data = None
    for raw in lines:
        line = raw.rstrip("\n")
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data = line[5:].strip()
        elif not line and event == "citations":
            break
    return json.loads(data or "[]")


def top_scores(question: str) -> tuple[list[float], float]:
    body = json.dumps({"question": question, "top_k": TOP_K}).encode()
    request = urllib.request.Request(
        f"{API_URL}/books/{BOOK_ID}/chat", data=body, headers={"Content-Type": "application/json"}
    )
    start = time.perf_counter()
    with urllib.request.urlopen(request, timeout=120) as response:
        cites = first_citations([raw.decode() for raw in response])
    return [float(c["score"]) for c in cites], time.perf_counter() - start  # type: ignore[arg-type]


def labelled(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    out = []
    for r in rows:
        if r["kind"] == "unanswerable":
            out.append({**r, "answerable": False, "split": r["split"]})
        else:
            out.append({**r, "answerable": True, "split": r["kind"]})
    return out


def main() -> None:
    lines = QUESTIONS.read_text(encoding="utf-8").splitlines()
    rows = labelled([json.loads(x) for x in lines if x])
    rows = rows[:LIMIT] if LIMIT else rows
    results = []
    for row in rows:
        scores, elapsed = top_scores(str(row["question"]))
        results.append(
            {
                "id": row["id"],
                "answerable": row["answerable"],
                "split": row["split"],
                "category": row.get("category"),
                "top_score": scores[0] if scores else None,
                "scores": scores,
                "retrieval_s": round(elapsed, 3),
            }
        )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"label": LABEL, "book_id": BOOK_ID, "top_k": TOP_K, "results": results}
    (OUT_DIR / f"abstain-scores-{LABEL}.json").write_text(
        json.dumps(payload, indent=1), encoding="utf-8"
    )
    print(f"{len(results)} questions scored -> abstain-scores-{LABEL}.json")


if __name__ == "__main__":
    main()
