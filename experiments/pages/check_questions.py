"""Check questions.jsonl against the manifest: one question per held-out page, none on dev pages.

Also prints, for each question, the share of its answer's words found on the page (a rough guard
against a question whose answer is not on the page; the owner's spot-check is the real check).
Usage: python check_questions.py DATA_DIR QUESTIONS.jsonl
"""

import json
import re
import sys
from pathlib import Path

data, qfile = Path(sys.argv[1]), Path(sys.argv[2])
manifest = {}
for line in (data / "manifest.jsonl").read_text(encoding="utf-8").splitlines():
    row = json.loads(line)
    manifest[row["id"]] = row
questions = [json.loads(x) for x in qfile.read_text(encoding="utf-8").splitlines() if x.strip()]
held = {k for k, v in manifest.items() if v["set"] == "heldout"}
ids = [q["page_id"] for q in questions]
assert len(questions) == 40, len(questions)
assert set(ids) == held and len(set(ids)) == 40, "questions must map 1:1 to held-out pages"
low = 0
for q in questions:
    text = (data / "text" / f"{q['page_id']}.txt").read_text(encoding="utf-8").lower()
    words = [w for w in re.findall(r"\w+", q["answer"].lower()) if len(w) > 2]
    share = sum(w in text for w in words) / max(1, len(words))
    if share < 0.5:
        low += 1
        print("LOW", q["page_id"], round(share, 2), q["answer"])
print(
    "ok: 40 questions, 1:1 with held-out pages;",
    low,
    "with less than half the answer words on the page",
)
