"""Does accent-insensitive or word-aware keyword search help Vietnamese retrieval? (#95)

Pre-registered rule (fixed before any result), on the harness of fts_options.py (#204): the same
208 blind questions, the same two corpora (P = the PDF's 392 chunks, H = the HTML's 359 chunks),
gap.py's scoring (a hit is a top-k chunk containing the evidence sentence), RRF k=60 and 30
candidates per leg, the dense leg fused with each keyword arm:

  A  BM25 over the `simple` lexemes (the shipped leg's quality ceiling, `bm25_py` in fts_options)
  B  the same BM25 with unaccent applied to chunk text and to the query
  C  the same BM25 over syllable unigrams plus adjacent-syllable bigrams (no segmenter library,
     so no new dependency; a stand-in for word segmentation, not a real segmenter)

Adopt B (or C) only if fused Hit@5 does not fall on either corpus and rises by at least 1.0 point
on at least one. Otherwise ship no app change.

Chunk text and stored bge-m3 vectors come from the corpora's own Postgres volumes (dumped to
DUMP_DIR as pdf.jsonl and html.jsonl with ordinal, text, emb); the dense leg is exact cosine in
numpy, which gives the order of the app's HNSW search with strict_order. Question vectors are
embedded by Ollama bge-m3 on CPU (num_gpu 0) and cached.

  BOOK_ID=x DUMP_DIR=<dir> uv run --with scipy python experiments/e2e/fts_accent.py
Writes experiments/e2e/results/fts-accent-95.json.
"""

from __future__ import annotations

import json
import os
import unicodedata
import urllib.request
from pathlib import Path
from typing import Any

os.environ.setdefault("BOOK_ID", "unused")
import itertools

import gap
import numpy as np

DUMP = Path(os.environ["DUMP_DIR"])
OUT = gap.HERE / "results" / "fts-accent-95.json"


def unaccent(s: str) -> str:
    s = unicodedata.normalize("NFD", unicodedata.normalize("NFC", s))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d").replace("Đ", "D")


def tok_plain(text: str) -> list[str]:
    return gap.WORD.findall(text.lower())


def tok_bigram(text: str) -> list[str]:
    t = tok_plain(text)
    return t + [f"{a}_{b}" for a, b in itertools.pairwise(t)]


def bm25_leg(texts: list[str], queries: list[str], tok: Any, fold: bool) -> list[list[int]]:
    def prep(s: str) -> str:
        return unaccent(s) if fold else s

    gap.tokens = tok  # BM25 in gap.py tokenises through this module-level function
    model = gap.BM25([prep(t) for t in texts])
    return gap.top_n(model.scores([prep(q) for q in queries]), gap.CANDIDATES)


def embed_queries(queries: list[str]) -> np.ndarray:
    def make() -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(queries), 16):
            body = json.dumps(
                {"model": "bge-m3", "input": queries[i : i + 16], "options": {"num_gpu": 0}}
            ).encode()
            req = urllib.request.Request(
                f"{gap.OLLAMA}/api/embed", data=body, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=1800) as r:
                out += json.loads(r.read())["embeddings"]
        return out

    return gap.cached("q_accent95", make)


def main() -> None:
    rows = [json.loads(x) for x in gap.QUESTIONS.read_text(encoding="utf-8").splitlines() if x]
    rows = [r for r in rows if r["kind"] == "blind"]
    queries = [r["question"] for r in rows]
    qv = embed_queries(queries)
    qv = qv / np.linalg.norm(qv, axis=1, keepdims=True)
    report: dict[str, Any] = {"questions": len(rows), "corpora": {}}
    for name, file in (("P", "pdf.jsonl"), ("H", "html.jsonl")):
        recs = [json.loads(x) for x in (DUMP / file).read_text(encoding="utf-8").splitlines()]
        texts = [r["text"] for r in recs]
        cv = np.asarray([json.loads(r["emb"]) for r in recs], dtype=np.float32)
        cv /= np.linalg.norm(cv, axis=1, keepdims=True)
        gold = [
            {i for i, t in enumerate(map(gap.norm, texts)) if gap.norm(r["evidence"]) in t}
            for r in rows
        ]
        assert all(gold)
        dense = gap.top_n(qv @ cv.T + 1.0, gap.CANDIDATES)
        legs = {
            "A bm25": bm25_leg(texts, queries, tok_plain, False),
            "B bm25 unaccent": bm25_leg(texts, queries, tok_plain, True),
            "C bm25 syllable bigrams": bm25_leg(texts, queries, tok_bigram, False),
        }
        arms: dict[str, list[list[int]]] = {"dense only": dense}
        for k, v in legs.items():
            arms[f"{k} alone"] = v
            arms[f"{k} + dense"] = [gap.rrf([d, x]) for d, x in zip(dense, v, strict=True)]
        res = {a: gap.score(r, gold) for a, r in arms.items()}
        base = res["A bm25 + dense"]["_hits5"]
        for arm in ("B bm25 unaccent", "C bm25 syllable bigrams"):
            h = res[f"{arm} + dense"]["_hits5"]
            res[f"{arm} + dense"]["gained_lost_vs_A"] = [
                sum(b > a for a, b in zip(base, h, strict=True)),
                sum(a > b for a, b in zip(base, h, strict=True)),
            ]
        for m in res.values():
            m.pop("_hits1"), m.pop("_hits5")
        report["corpora"][name] = {"chunks": len(texts), "arms": res}
        print(f"\ncorpus {name}: {len(texts)} chunks")
        for a, m in res.items():
            print(
                f"  {a:34s} Hit@1 {m['hit@1']:5.1f}  Hit@5 {m['hit@5']:5.1f}  "
                f"{m['hit@5_ci95']}  {m.get('gained_lost_vs_A', '')}"
            )
    OUT.write_text(json.dumps(report, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
