"""Build the human labelling sheet from a collection of real answers (#244).

40 rows, shuffled, written as a CSV the human fills in:

  row_id, question, reference, passages, answer, score, note

`score` is left EMPTY: the agent that builds the sheet never fills in a label. The system that
wrote each answer (`topk6` or `topk1`), the question id and kind are NOT in the sheet; they go to a
separate key file the judge does not read (the judge's prompt is built from the same columns as the
sheet and nothing else). Open the key only after labelling.

The 40 rows: 16 `topk6` and 12 `topk1` answers to answerable questions, and 6 + 6 answers of each
system to unanswerable ones (abstentions and made-up answers alike).

  uv run python evals/judge_sheet.py

Environment: JUDGE_IN (experiments/judge/collection.json), SEED (244),
SHEET (experiments/judge/labelling-sheet.csv), KEY (experiments/judge/labelling-key.csv).
"""

from __future__ import annotations

import csv
import json
import os
import random
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from answer_judge import format_passages

ROOT = Path(__file__).resolve().parent.parent
SHEET_COLUMNS = ("row_id", "question", "reference", "passages", "answer", "score", "note")
KEY_COLUMNS = ("row_id", "system", "qid", "kind", "abstained")
# (system, kind, rows on the sheet)
SHEET_PLAN: Sequence[tuple[str, str, int]] = (
    ("topk6", "answerable", 16),
    ("topk1", "answerable", 12),
    ("topk6", "unanswerable", 6),
    ("topk1", "unanswerable", 6),
)


def select_rows(
    rows: Sequence[Mapping[str, Any]], plan: Sequence[tuple[str, str, int]], seed: int
) -> list[Mapping[str, Any]]:
    """The sheet's rows, shuffled. Raises when the collection has too few of a cell."""
    rng = random.Random(seed)
    chosen: list[Mapping[str, Any]] = []
    for system, kind, count in plan:
        cell = [
            r
            for r in rows
            if r["system"] == system and (r["kind"] == "unanswerable") == (kind == "unanswerable")
        ]
        if len(cell) < count:
            raise ValueError(f"{system}/{kind}: {len(cell)} rows, need {count}")
        chosen += rng.sample(cell, count)
    rng.shuffle(chosen)
    return chosen


def sheet_row(row: Mapping[str, Any]) -> dict[str, str]:
    """Exactly what the human (and the judge) sees; `score` empty."""
    return {
        "row_id": row["row_id"],
        "question": row["question"],
        "reference": row["reference"],
        "passages": format_passages(row["passages"]),
        "answer": row["answer"],
        "score": "",
        "note": "",
    }


def write_sheet(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:  # BOM: Excel reads UTF-8
        writer = csv.DictWriter(f, fieldnames=SHEET_COLUMNS)
        writer.writeheader()
        writer.writerows(sheet_row(r) for r in rows)


def write_key(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=KEY_COLUMNS)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r[k] for k in KEY_COLUMNS})


def main() -> None:
    env = os.environ
    source = Path(env.get("JUDGE_IN", ROOT / "experiments" / "judge" / "collection.json"))
    rows = json.loads(source.read_text(encoding="utf-8"))["rows"]
    chosen = select_rows(rows, SHEET_PLAN, int(env.get("SEED", "244")))
    sheet = Path(env.get("SHEET", ROOT / "experiments" / "judge" / "labelling-sheet.csv"))
    key = Path(env.get("KEY", ROOT / "experiments" / "judge" / "labelling-key.csv"))
    write_sheet(sheet, chosen)
    write_key(key, chosen)
    print(f"{len(chosen)} rows: {sheet} (score column empty); key: {key}")


if __name__ == "__main__":
    main()
