"""Book test set v2 (issue #178): stronger blind rewrites, closed-book filter, varied unanswerables.

Rules are pre-registered in PREREG-178.md and are not changed after results. Subcommands:

  baseline                 overlap of the committed (v1) questions with their source chunk
  todo-rewrite             print the seen questions (nothing else) for the blind rewrite
  apply-rewrite FILE       apply rewrites from FILE ({id: question}); keep those under the threshold
  todo-closed              print the seen questions (no answers) for the closed-book answers
  score-closed FILE        grade closed-book answers ({id: answer}) with the deterministic rule
  check-unanswerable FILE  check the 25 new unanswerable questions against the rules
  build                    write questions.v2.jsonl from the intermediate files in data/v2/

Run from the repository root with `uv run python -I experiments/book-testset/testset_v2.py ...`
after `fetch_book.py` (it needs data/chunks.jsonl).
"""

from __future__ import annotations

import json
import random
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
DATA = HERE / "data"
V2 = DATA / "v2"
OVERLAP_MAX = 0.50  # pre-registered
RECALL_MIN = 0.60  # pre-registered
MAX_SHARE = 0.30
UNANS_OVERLAP_FLAG = 0.80
# Pairs whose answers the author saw before the closed-book rule was written keep their v1
# verdict.
SEEN_ANSWER = {"c0-seen", "c2-seen", "c6-seen"}
# Blind rewrites the self-review (Claude, not independent) flagged; see review-v2.md.
FLAGGED = {"c3", "c8", "c122", "c26", "c27", "c33", "c74", "c84"}
TOKEN = re.compile(r"\w+", re.UNICODE)


def tokens(text: str) -> list[str]:
    return TOKEN.findall(unicodedata.normalize("NFC", text).lower().replace("-", " "))


def load(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def overlap(question: str, chunk_text: str) -> float:
    q = set(tokens(question))
    return len(q & set(tokens(chunk_text))) / max(len(q), 1)


def recall(reference: str, answer: str) -> float:
    ref = set(tokens(reference))
    return len(ref & set(tokens(answer))) / max(len(ref), 1)


def dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    cmd = sys.argv[1]
    chunks = [c["text"] for c in load(DATA / "chunks.jsonl")]
    rows = load(HERE / "questions.jsonl")
    seen = [q for q in rows if q["kind"] == "seen"]
    blind = {q["source_id"]: q for q in rows if q["kind"] == "blind"}
    V2.mkdir(parents=True, exist_ok=True)

    if cmd == "baseline":
        for kind, rs in (("seen", seen), ("blind", list(blind.values()))):
            ov = [overlap(q["question"], chunks[q["source_chunk"]]) for q in rs]
            print(
                kind,
                len(rs),
                "mean",
                round(sum(ov) / len(ov), 3),
                "share<=0.50",
                round(sum(o <= OVERLAP_MAX for o in ov) / len(ov), 3),
            )
    elif cmd == "todo-rewrite":
        for q in seen:
            print(q["id"], "|", q["question"])
    elif cmd == "todo-closed":
        for q in seen:
            if q["id"] not in SEEN_ANSWER:
                print(q["id"], "|", q["question"])
    elif cmd == "apply-rewrite":
        new: dict[str, str] = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        out = {}
        for sid, text in new.items():
            ov = overlap(text, chunks[blind[sid]["source_chunk"]])
            out[sid] = {"question": text, "overlap": round(ov, 3), "kept": ov <= OVERLAP_MAX}
        dest = V2 / f"rewrite-{Path(sys.argv[2]).stem}.json"
        dest.write_text(dump(out), encoding="utf-8")
        kept = [v for v in out.values() if v["kept"]]
        print(
            f"{len(out)} rewrites, {len(kept)} kept, mean overlap all "
            f"{sum(v['overlap'] for v in out.values()) / len(out):.3f}, "
            f"kept {sum(v['overlap'] for v in kept) / max(len(kept), 1):.3f}"
        )
    elif cmd == "score-closed":
        ans: dict[str, str] = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        by_id = {q["id"]: q for q in seen}
        out = {
            i: {
                "recall": round(recall(by_id[i]["answer"], a), 3),
                "correct": recall(by_id[i]["answer"], a) >= RECALL_MIN,
            }
            for i, a in ans.items()
        }
        (V2 / "closed.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"{len(out)} graded, {sum(v['correct'] for v in out.values())} correct")
    elif cmd == "check-unanswerable":
        qs: list[dict[str, str]] = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        hand = {q["question"] for q in rows if q.get("generator") == "hand-written"}
        cats: dict[str, int] = {}
        for q in qs:
            cats[q["category"]] = cats.get(q["category"], 0) + 1
            q["max_overlap"] = round(max(overlap(q["question"], c) for c in chunks), 3)
            q["flag"] = q["max_overlap"] >= UNANS_OVERLAP_FLAG
        n = len(qs)
        print("n", n, "categories", cats)
        print("max share", round(max(cats.values()) / n, 2), "distinct", len(cats))
        print(
            "archaeology mentions",
            sum(bool(re.search(r"khảo cổ|archaeolog", q["question"], re.I)) for q in qs),
        )
        print("duplicates of hand-written", sum(q["question"] in hand for q in qs))
        print("flagged for review (overlap >= 0.80):", [q["id"] for q in qs if q["flag"]])
        (V2 / "unanswerable-checked.json").write_text(
            json.dumps(qs, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    elif cmd == "build":
        closed = json.loads((V2 / "closed.json").read_text(encoding="utf-8"))
        first = json.loads((V2 / "rewrite-rw1.json").read_text(encoding="utf-8"))
        second = json.loads((V2 / "rewrite-rw2.json").read_text(encoding="utf-8"))
        unans = json.loads((V2 / "unanswerable-checked.json").read_text(encoding="utf-8"))
        out: list[dict[str, Any]] = []
        for q in seen:
            q = dict(q)
            q["closed_book_v1"] = q["closed_book_correct"]
            if q["id"] in closed:
                q["closed_book_correct"] = closed[q["id"]]["correct"]
            q["closed_book_by"] = "claude-sonnet-5-5" if q["id"] in closed else "v1"
            out.append(q)
            pick = first.get(q["id"]) if first[q["id"]]["kept"] else second.get(q["id"])
            if pick and pick["kept"]:
                b = dict(blind[q["id"]])
                b["question_v1"] = b["question"]
                b["question"] = pick["question"]
                b["rewrite_overlap"] = pick["overlap"]
                b["closed_book_correct"] = q["closed_book_correct"]
                b["generator"] = "claude-sonnet-5-5"
                b["review_flag"] = q["id"].removesuffix("-seen") in FLAGGED
                out.append(b)
        out += [r for r in rows if r.get("generator") == "hand-written"]
        for i, u in enumerate(unans):
            out.append(
                {
                    "id": f"uv2-{i}",
                    "kind": "unanswerable",
                    "question": u["question"],
                    "source_id": f"uv2-{i}",
                    "source_chunk": None,
                    "gold_chunks": [],
                    "section_path": None,
                    "category": u["category"],
                    "generator": "claude-sonnet-5-5",
                    "answerable": False,
                    "split": "seen" if i < 13 else "blind",
                }
            )
        text = "\n".join(json.dumps(r, ensure_ascii=False) for r in out) + "\n"
        (HERE / "questions.v2.jsonl").write_text(text, encoding="utf-8")
        kinds: dict[str, int] = {}
        for r in out:
            kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
        needed = sum(1 for r in out if r["kind"] == "blind" and not r["closed_book_correct"])
        print(kinds, "blind retrieval-needed", needed)
    elif cmd == "control":
        ids = sorted(q["id"] for q in seen)
        print(random.Random(178).sample(ids, 10))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
