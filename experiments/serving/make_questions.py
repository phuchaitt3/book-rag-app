"""Pick the 33 questions (3 warm-up + 30 counted) for the serving-latency run (issue #190).

Takes the "blind" questions of experiments/book-testset/questions.jsonl, sorts by id, samples
33 with random.Random(2026) and writes questions.json next to this file.
"""

import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "book-testset" / "questions.jsonl"


def full() -> None:
    """All 208 blind questions in id order, preceded by the 3 warm-up ones of questions.json.

    Writes questions-208.json: 3 warm-up (the first 3 of questions.json, so they are the same
    as in #190) then the 208 counted questions (#259). The warm-up questions also appear
    among the 208; they are measured twice and only the second time counts.
    """
    rows = [json.loads(line) for line in SOURCE.read_text(encoding="utf-8").splitlines() if line]
    blind = sorted((r for r in rows if r["kind"] == "blind"), key=lambda r: r["id"])
    warm = json.loads((HERE / "questions.json").read_text(encoding="utf-8"))[:3]
    out = warm + [{"id": r["id"], "question": r["question"]} for r in blind]
    (HERE / "questions-208.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(out)} questions (3 warm-up + {len(blind)} counted)")


def main() -> None:
    rows = [json.loads(line) for line in SOURCE.read_text(encoding="utf-8").splitlines() if line]
    blind = sorted((r for r in rows if r["kind"] == "blind"), key=lambda r: r["id"])
    picked = random.Random(2026).sample(blind, 33)
    out = [{"id": r["id"], "question": r["question"]} for r in picked]
    (HERE / "questions.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(out)} questions")


if __name__ == "__main__":
    import sys

    full() if "--full" in sys.argv else main()
