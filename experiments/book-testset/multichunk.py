"""Multi-chunk question set (issue #183): span draw, gold building, Recall@k scoring.

Rules are pre-registered in PREREG-183.md and are not changed after results. Subcommands
(run from the repository root, after `fetch_book.py`, with `uv run python -I`):

  spans                    draw the 60 candidate spans (seed 183) into data/multi/spans.json
  show A B                 print the chunks of candidate spans A..B-1 for the writer
  build FILE               turn the written questions in FILE into questions.multi.jsonl
  check                    leakage guard and word overlap for questions.multi.jsonl
  control [FLAGS]          print the control sample of unflagged questions (seed 183)
  score [RANKINGS]         Recall@k, Hit@k, All@k with bootstrap intervals; with no file it
                           ranks with BM25 alone (CPU only) and with a random floor

A rankings file is JSON, {question id: [chunk ids, best first]}, so any arm can be scored.
"""

from __future__ import annotations

import json
import math
import random
import re
import sys
import unicodedata
from collections import Counter
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).parent
DATA = HERE / "data"
MULTI = DATA / "multi"
OUT = HERE / "questions.multi.jsonl"
SEED = 183
N_SPANS = 60
SIZES = [2] * 12 + [3] * 12 + [4] * 6  # per 30 spans, repeated for the 60 candidates
MIN_CHARS = 300
MIN_GAP = 2
N_BOOT = 2000
KS = (1, 5, 10)
TOKEN = re.compile(r"\w+", re.UNICODE)


def tokens(text: str) -> list[str]:
    # Same as bench.py: lowercase words, no stemming (close to to_tsvector('simple')).
    return TOKEN.findall(text.lower())


def norm(text: str) -> str:
    return " ".join(tokens(unicodedata.normalize("NFC", text)))


def load(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


# ---------------------------------------------------------------- spans


def draw_spans(chunks: list[dict[str, Any]], seed: int = SEED, n: int = N_SPANS) -> list[list[int]]:
    """Spans of 2-4 chunks in one section, at least MIN_GAP apart, no chunk used twice."""
    rng = random.Random(seed)
    by_section: dict[int, list[int]] = {}
    for i, c in enumerate(chunks):
        if len(c["text"]) >= MIN_CHARS and "Phụ lục" not in c["section_path"]:
            by_section.setdefault(c["section_index"], []).append(i)
    sizes = (SIZES * math.ceil(n / len(SIZES)))[:n]
    rng.shuffle(sizes)
    used: set[int] = set()
    spans: list[list[int]] = []
    for size in sizes:
        for _ in range(200):
            sections = [s for s, ids in by_section.items() if len(ids) >= size]
            weights = [len(by_section[s]) for s in sections]
            ids = [i for i in by_section[rng.choices(sections, weights)[0]] if i not in used]
            if len(ids) < size:
                continue
            pick = sorted(rng.sample(ids, size))
            if all(b - a >= MIN_GAP for a, b in pairwise(pick)):
                spans.append(pick)
                used.update(pick)
                break
    return spans


# ---------------------------------------------------------------- gold


def copies_of(evidence: str, chunks: list[dict[str, Any]]) -> list[int]:
    """Every chunk holding the evidence sentence (the overlap copies), by position."""
    e = norm(evidence)
    return [i for i, c in enumerate(chunks) if e and e in norm(c["text"])]


def build_rows(
    written: list[dict[str, Any]], spans: list[list[int]], chunks: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Questions with one gold group per required chunk; returns (rows, problems)."""
    rows: list[dict[str, Any]] = []
    problems: list[str] = []
    for w in written:
        qid = f"m{w['span']}"
        span = spans[w["span"]]
        required = []
        for r in w["required"]:
            copies = copies_of(r["evidence"], chunks)
            if r["chunk"] not in copies:
                problems.append(f"{qid}: evidence not in chunk {r['chunk']}")
            required.append({"chunk": r["chunk"], "evidence": r["evidence"], "copies": copies})
        if sorted(r["chunk"] for r in required) != span:
            problems.append(f"{qid}: required chunks differ from the span {span}")
        sections = {chunks[c]["section_path"] for c in span}
        rows.append(
            {
                "id": qid,
                "kind": "multi",
                "question": w["question"],
                "answer": w["answer"],
                "span": span,
                "n_required": len(required),
                "required": required,
                "gold_groups": [r["copies"] for r in required],
                "section_path": sorted(sections)[0],
                "closed_book_correct": None,
                "generator": "claude-sonnet-5-5",
            }
        )
    return rows, problems


# ---------------------------------------------------------------- scoring


def found_groups(ranked: list[int], groups: list[list[int]], k: int) -> int:
    """Number of required chunks with any copy in the top k."""
    top = set(ranked[:k])
    return sum(1 for g in groups if top & set(g))


def per_question(
    rankings: list[list[int]], groups: list[list[list[int]]], k: int
) -> dict[str, np.ndarray]:
    rec, hit, full = [], [], []
    for ranked, g in zip(rankings, groups, strict=True):
        f = found_groups(ranked, g, k)
        rec.append(f / len(g))
        hit.append(float(f >= 1))
        full.append(float(f == len(g)))
    return {
        f"recall@{k}": np.array(rec),
        f"hit@{k}": np.array(hit),
        f"all@{k}": np.array(full),
    }


def interval(values: np.ndarray, boot: np.ndarray) -> dict[str, float]:
    means = values[boot].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return {"mean": float(values.mean()), "lo": float(lo), "hi": float(hi)}


def boot_indices(n: int, seed: int = SEED, n_boot: int = N_BOOT) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, n, size=(n_boot, n))


# ---------------------------------------------------------------- BM25 (as bench.py)


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.2, b: float = 0.75) -> None:
        self.k1 = k1
        self.tf = [Counter(tokens(d)) for d in docs]
        dl = [sum(c.values()) for c in self.tf]
        avg = sum(dl) / len(docs)
        df: Counter[str] = Counter()
        for c in self.tf:
            df.update(c.keys())
        n = len(docs)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}
        self.norm = [k1 * (1 - b + b * length / avg) for length in dl]

    def rank(self, query: str) -> list[int]:
        q = Counter(tokens(query))
        scores = []
        for tf, nm in zip(self.tf, self.norm, strict=True):
            s = 0.0
            for t, qc in q.items():
                c = tf.get(t)
                if c:
                    s += qc * c * (self.k1 + 1) / (c + nm) * self.idf[t]
            scores.append(s)
        return sorted(range(len(scores)), key=lambda i: (-scores[i], i))


def score_arm(
    name: str, rankings: list[list[int]], rows: list[dict[str, Any]], boot: np.ndarray
) -> dict[str, Any]:
    groups = [r["gold_groups"] for r in rows]
    out: dict[str, Any] = {"arm": name}
    per: dict[str, np.ndarray] = {}
    for k in KS:
        per.update(per_question(rankings, groups, k))
    for key, v in per.items():
        out[key] = interval(v, boot)
    sizes = np.array([r["n_required"] for r in rows])
    out["by_size"] = {
        str(s): {
            key: round(float(per[key][sizes == s].mean()), 4)
            for key in ("recall@5", "hit@5", "all@5")
        }
        for s in sorted({int(x) for x in sizes})
    }
    out["_per"] = per
    return out


def paired(a: dict[str, Any], b: dict[str, Any], key: str, boot: np.ndarray) -> dict[str, float]:
    return interval(a["_per"][key] - b["_per"][key], boot)


def fmt(iv: dict[str, float]) -> str:
    return f"{100 * iv['mean']:.1f} ({100 * iv['lo']:.1f}-{100 * iv['hi']:.1f})"


# ---------------------------------------------------------------- commands


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    chunks = load(DATA / "chunks.jsonl")
    MULTI.mkdir(parents=True, exist_ok=True)
    if cmd == "spans":
        spans = draw_spans(chunks)
        (MULTI / "spans.json").write_text(json.dumps(spans), encoding="utf-8")
        print(len(spans), "spans", Counter(len(s) for s in spans))
        return
    spans = json.loads((MULTI / "spans.json").read_text(encoding="utf-8"))
    if cmd == "show":
        for si in range(int(sys.argv[2]), int(sys.argv[3])):
            print(f"\n######## SPAN {si}  chunks {spans[si]}")
            for c in spans[si]:
                print(f"\n--- chunk {c} [{chunks[c]['section_path']}]\n{chunks[c]['text']}")
    elif cmd == "build":
        written = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        rows, problems = build_rows(written, spans, chunks)
        for p in problems:
            print("PROBLEM", p)
        rows = [r for r in rows if not any(p.startswith(r["id"] + ":") for p in problems)]
        OUT.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
        )
        print(len(rows), "questions written to", OUT, Counter(r["n_required"] for r in rows))
    elif cmd == "check":
        rows = load(OUT)
        norm_chunks = [norm(c["text"]) for c in chunks]
        leaks = sum(any(norm(r["question"]) in p for p in norm_chunks) for r in rows)
        words = [set(tokens(c["text"])) for c in chunks]
        ov = [
            len(set(tokens(r["question"])) & set().union(*(words[c] for c in r["span"])))
            / max(len(set(tokens(r["question"]))), 1)
            for r in rows
        ]
        share = float(np.mean([len(g) for r in rows for g in r["gold_groups"]]))
        print(f"{len(rows)} questions, leaks {leaks}, mean overlap with span {np.mean(ov):.3f}")
        print(f"mean copies per required chunk {share:.2f}")
        if leaks:
            raise SystemExit("leakage")
    elif cmd == "control":
        flagged = (
            set(json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")))
            if len(sys.argv) > 2
            else set()
        )
        ids = sorted(r["id"] for r in load(OUT) if r["id"] not in flagged)
        print(random.Random(SEED).sample(ids, 8))
    elif cmd == "score":
        rows = load(OUT)
        boot = boot_indices(len(rows))
        arms: dict[str, list[list[int]]] = {}
        if len(sys.argv) > 2:
            ranked = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
            arms[Path(sys.argv[2]).stem] = [ranked[r["id"]] for r in rows]
        else:
            bm = BM25([c["text"] for c in chunks])
            arms["bm25_only"] = [bm.rank(r["question"]) for r in rows]
            rng = random.Random(SEED)
            arms["random_floor"] = [rng.sample(range(len(chunks)), len(chunks)) for _ in rows]
        scored = {n: score_arm(n, rk, rows, boot) for n, rk in arms.items()}
        for s in scored.values():
            print(
                s["arm"], {k: fmt(v) for k, v in s.items() if isinstance(v, dict) and "mean" in v}
            )
            print("  by size", s["by_size"])
        if "bm25_only" in scored:
            d = paired(scored["bm25_only"], scored["random_floor"], "recall@5", boot)
            print("bm25 - random, Recall@5:", fmt(d))
        dump = {n: {k: v for k, v in s.items() if k != "_per"} for n, s in scored.items()}
        (MULTI / "results.json").write_text(json.dumps(dump, indent=1), encoding="utf-8")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
