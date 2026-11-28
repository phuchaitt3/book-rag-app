# ruff: noqa: E501
"""Build the #291 question files from drafts.py, the review and the sample (PREREG-291.md).

  uv run python experiments/abstain/build_set.py prepare   # checks + review input
  uv run python experiments/abstain/build_set.py build     # apply the review, write the files

`prepare` writes data/review-input.json (git-ignored): every draft with its category, its
overlap checks and the five chunks closest by word overlap. `build` reads data/review-output.json
({id: {"label", "passage", "note"}}) and writes questions.abstain.jsonl (kept questions),
review-291.md (every verdict) and human-sample-291.md (the owner's sample, seed 291).
"""

from __future__ import annotations

import json
import random
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

from drafts import P, U

HERE = Path(__file__).parent
BOOK = HERE.parent / "book-testset"
DATA = BOOK / "data"
TOKEN = re.compile(r"\w+", re.UNICODE)
MIN_U, MIN_CAT, MAX_SHARE = 100, 12, 0.25  # PREREG-291 section 2


def tokens(text: str) -> list[str]:
    return TOKEN.findall(unicodedata.normalize("NFC", text).lower().replace("-", " "))


def overlap(question: str, chunk: str) -> float:
    q = set(tokens(question))
    return len(q & set(tokens(chunk))) / max(len(q), 1)


def load(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def drafts() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for cat, qs in U.items():
        for i, q in enumerate(qs):
            rows.append(
                {"id": f"u3-{cat}-{i:02d}", "kind": "unanswerable", "category": cat, "question": q}
            )
    for i, (chunk, q) in enumerate(P):
        rows.append({"id": f"p3-{i:02d}", "kind": "partial", "gold_chunk": chunk, "question": q})
    return rows


def prepare() -> None:
    chunks = [c["text"] for c in load(DATA / "chunks.jsonl")]
    old = {
        unicodedata.normalize("NFC", r["question"]).lower()
        for p in ("questions.jsonl", "questions.v2.jsonl")
        for r in load(BOOK / p)
    }
    out = []
    for row in drafts():
        ov = sorted(((overlap(row["question"], c), i) for i, c in enumerate(chunks)), reverse=True)[
            :5
        ]
        row = {
            **row,
            "max_overlap": round(ov[0][0], 3),
            "duplicate": unicodedata.normalize("NFC", row["question"]).lower() in old,
            "archaeology": "khảo cổ" in row["question"].lower(),
            "closest_chunks": [
                {"chunk": i, "overlap": round(o, 3), "text": chunks[i][:700]} for o, i in ov
            ],
        }
        out.append(row)
    (DATA / "review-input.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    flagged = [
        r["id"] for r in out if r["max_overlap"] >= 0.8 or r["duplicate"] or r["archaeology"]
    ]
    print(len(out), "drafts; flagged for the chunk check / duplicate / archaeology:", flagged)
    print(Counter(r["kind"] for r in out))


def build() -> None:
    rows = {
        r["id"]: r for r in json.loads((DATA / "review-input.json").read_text(encoding="utf-8"))
    }
    verdict = json.loads((DATA / "review-output.json").read_text(encoding="utf-8"))
    want = {"unanswerable": "unanswerable", "partial": "partial"}
    kept = []
    for rid, row in rows.items():
        v = verdict[rid]
        row["review"] = v
        if v["label"] == want[row["kind"]]:
            kept.append(row)
    unans = [r for r in kept if r["kind"] == "unanswerable"]
    partial = [r for r in kept if r["kind"] == "partial"]
    per_cat = Counter(r["category"] for r in unans)
    print("kept U", len(unans), dict(per_cat), "kept P", len(partial))
    problems = []
    if len(unans) < MIN_U:
        problems.append(f"only {len(unans)} unanswerable questions kept (< {MIN_U})")
    for cat in U:
        if per_cat[cat] < MIN_CAT:
            problems.append(f"category {cat} has {per_cat[cat]} (< {MIN_CAT})")
        if per_cat[cat] > MAX_SHARE * len(unans):
            problems.append(f"category {cat} over {MAX_SHARE:.0%}")
    if len(partial) < 30:
        problems.append(f"only {len(partial)} partial questions kept (< 30)")
    if problems:
        print("PREREG RULES NOT MET:", problems)
    out = HERE / "questions.abstain.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for r in unans + partial:
            rec = {
                "id": r["id"],
                "kind": r["kind"],
                "question": r["question"],
                "answerable": False if r["kind"] == "unanswerable" else None,
                "split": "blind",
                "category": r.get("category", "partial"),
                "gold_chunks": [r["gold_chunk"]] if r["kind"] == "partial" else [],
                "generator": "claude-sonnet-5-5",
                "reviewer": "see review-291.md",
                "max_overlap": r["max_overlap"],
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    lines = [
        "# Review of the #291 drafts",
        "",
        "Verdicts of the reviewing model for every draft (kept and dropped).",
        "",
    ]
    lines += ["| id | kind | category | verdict | passage | note |", "|---|---|---|---|---|---|"]
    for rid, r in rows.items():
        v = r["review"]
        lines.append(
            f"| {rid} | {r['kind']} | {r.get('category', '-')} | {v['label']} | {v.get('passage') or ''} | "
            f"{str(v.get('note', '')).replace('|', '/')} |"
        )
    (HERE / "review-291.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    # The owner's sample: 3 per pattern from U, 9 from P, fixed by seed 291, drawn before any score.
    rng = random.Random(291)
    sample: list[dict[str, Any]] = []
    for cat in U:
        sample += rng.sample(
            sorted((r for r in unans if r["category"] == cat), key=lambda r: r["id"]), 3
        )
    sample += rng.sample(sorted(partial, key=lambda r: r["id"]), 9)
    md = [
        "# Human spot check for #291 (about 10 minutes)",
        "",
        "30 questions about *Việt Nam sử lược, Quyển I*. For each, read the question and the closest passage the",
        "script found, and mark whether the **label is right**: `U` = the book does not answer it at all;",
        "`P` = the book answers one part and not the other. Tick the box when the label is right, leave it empty",
        "and write a few words when it is wrong (for example: 'the book does say it, passage 123').",
        "The closest passage may not be the one that answers it; use Ctrl+F on the book if a label looks wrong.",
        "",
    ]
    for n, r in enumerate(sample, 1):
        top = r["closest_chunks"][0]
        md += [
            f"{n}. [ ] **{r['id']}** ({'U, ' + r['category'] if r['kind'] == 'unanswerable' else 'P'})",
            f"   Question: {r['question']}",
            f"   Closest passage (chunk {top['chunk']}): {top['text'][:420]}",
            "",
        ]
    (HERE / "human-sample-291.md").write_text("\n".join(md), encoding="utf-8")
    print("sample ids:", [r["id"] for r in sample])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    {"prepare": prepare, "build": build}[sys.argv[1]]()
