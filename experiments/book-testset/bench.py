"""Retrieval benchmark on the book test set: Việt Nam sử lược, Quyển I (#177).

Same arms, metrics and bootstrap as experiments/viquad-bench (#171, #173, #175), over the
app's own chunks of one book instead of Wikipedia passages:
  2 distiluse-base-multilingual-cased-v1 over chunks (v1's model).
  3 bge-m3 over chunks.
  4 bge-m3 + BM25 fused with reciprocal rank fusion, k=60, 30 candidates per list
    (as packages/rag/src/book_rag/retrieval/hybrid.py does).
  5 arm 4 + bge-reranker-v2-m3 over the fused top 20.
Arm 1 (v1's index of questions) has no counterpart: no generated-question index of this
book exists yet, and one would need a generator other than the one that wrote these
questions (docs/benchmarks/README.md, checklist item 2).

Query sets, from questions.jsonl (generate.py):
  seen   questions written with the chunk in view.
  blind  the same questions rewritten without the chunk in view (as #173's sets).
  *_retrieval_needed  the subset the generator could not answer without the book (the
         standard's filter: drop questions answerable without retrieval).
A hit is any gold chunk (the source chunk, or another chunk holding the same evidence
sentence, which chunk overlap creates) in the top k. Unanswerable questions are counted,
not scored.

Leakage guard (#175, adapted): the index is the book's chunks only, so no query or source
question can be in it unless a question copies a whole chunk. Before any model runs, the
script checks each query's normalised text against every chunk and stops if a chunk
contains it; it reports near-copies (cosine >= 0.95 to a chunk) and each set's word
overlap with its gold chunk. CHECK_ONLY=1 runs only that, without the models.

Run from the repository root (GPU used when torch sees one; SKIP_RERANK=1 skips arm 5):
  uv run --with sentence-transformers --with scipy --with torch \
    --index https://download.pytorch.org/whl/cu128 python experiments/book-testset/bench.py
"""

from __future__ import annotations

import json
import os
import platform
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

OUT = Path(os.environ.get("OUT_DIR", Path(__file__).parent / "data"))
QUESTIONS = Path(os.environ.get("QUESTIONS", OUT / "questions.jsonl"))
SEED = 177
TOP_K = 10
CANDIDATES = 30
RRF_K = 60
RERANK_DEPTH = 20
N_BOOT = 2000
NEAR_DUP = 0.95
SKIP_RERANK = os.environ.get("SKIP_RERANK") == "1"
CHECK_ONLY = os.environ.get("CHECK_ONLY") == "1"
T_START = time.perf_counter()
timings: dict[str, float] = {}


def log(msg: str) -> None:
    print(f"[{time.perf_counter() - T_START:7.1f}s] {msg}", flush=True)


TOKEN = re.compile(r"\w+", re.UNICODE)


def tokens(text: str) -> list[str]:
    # Close to Postgres to_tsvector('simple', ...): lowercase words, no stemming.
    return TOKEN.findall(text.lower())


def normalise(text: str) -> str:
    return " ".join(tokens(text))


# ---------------------------------------------------------------- data
chunks = [json.loads(x) for x in (OUT / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
passages = [c["text"] for c in chunks]
questions = [json.loads(x) for x in QUESTIONS.read_text(encoding="utf-8").splitlines()]
scored = [q for q in questions if q["kind"] != "unanswerable"]
log(f"{len(passages)} chunks, {len(questions)} questions ({len(scored)} scored)")

query_sets: dict[str, list[dict[str, Any]]] = {}
for kind in ("seen", "blind"):
    rows = [q for q in scored if q["kind"] == kind]
    query_sets[kind] = rows
    query_sets[f"{kind}_retrieval_needed"] = [q for q in rows if not q["closed_book_correct"]]

# ---------------------------------------------------------------- leakage guard
norm_passages = [normalise(p) for p in passages]
passage_words = [set(tokens(p)) for p in passages]
leak_report: dict[str, Any] = {}
for name, rows in query_sets.items():
    by_id = {q["id"]: q for q in scored}
    leaks = 0
    for q in rows:
        texts = {normalise(q["question"]), normalise(by_id[q["source_id"]]["question"])}
        leaks += any(t and t in p for t in texts for p in norm_passages)
    overlap = [
        len(set(tokens(q["question"])) & passage_words[q["source_chunk"]])
        / max(len(set(tokens(q["question"]))), 1)
        for q in rows
    ]
    leak_report[name] = {
        "queries_in_index": leaks,
        "mean_word_overlap_with_gold": round(float(np.mean(overlap)), 3) if rows else None,
    }
    if leaks:
        raise SystemExit(f"leakage: {leaks} queries of {name} are contained in a chunk")
log(f"leakage check passed: {json.dumps(leak_report)}")
if CHECK_ONLY:
    raise SystemExit(0)

# ---------------------------------------------------------------- models
import torch  # noqa: E402
from scipy import sparse  # noqa: E402
from sentence_transformers import CrossEncoder, SentenceTransformer  # noqa: E402

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
log(f"device={DEVICE} gpu={torch.cuda.get_device_name(0) if DEVICE == 'cuda' else '-'}")


def encode(model: SentenceTransformer, texts: list[str], batch: int) -> np.ndarray:
    return model.encode(
        texts,
        batch_size=batch,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    ).astype(np.float32)


def top_n(scores: np.ndarray, n: int) -> np.ndarray:
    n = min(n, scores.shape[1] - 1)
    part = np.argpartition(-scores, n, axis=1)[:, :n]
    order = np.take_along_axis(scores, part, axis=1).argsort(axis=1)[:, ::-1]
    return np.take_along_axis(part, order, axis=1)


def rrf(rankings: list[list[int]], k: int = RRF_K) -> list[int]:
    # Same rule as book_rag.retrieval.fusion.reciprocal_rank_fusion.
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return [item for item, _ in sorted(scores.items(), key=lambda p: p[1], reverse=True)]


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.2, b: float = 0.75) -> None:
        self.vocab: dict[str, int] = {}
        data, ind, ptr, lengths = [], [], [0], []
        for d in docs:
            counts = Counter(tokens(d))
            lengths.append(sum(counts.values()))
            for t, c in counts.items():
                ind.append(self.vocab.setdefault(t, len(self.vocab)))
                data.append(c)
            ptr.append(len(ind))
        shape = (len(docs), len(self.vocab))
        tf = sparse.csr_matrix((np.array(data, dtype=np.float32), ind, ptr), shape=shape)
        dl = np.array(lengths, dtype=np.float32)
        df = np.bincount(tf.indices, minlength=len(self.vocab))
        idf = np.log(1 + (len(docs) - df + 0.5) / (df + 0.5)).astype(np.float32)
        norm = k1 * (1 - b + b * dl / dl.mean())
        w = tf.tocoo()
        vals = w.data * (k1 + 1) / (w.data + norm[w.row]) * idf[w.col]
        self.weights = sparse.csr_matrix((vals, (w.row, w.col)), shape=shape)

    def scores(self, queries: list[str]) -> np.ndarray:
        data, ind, ptr = [], [], [0]
        for q in queries:
            for t, c in Counter(tokens(q)).items():
                if t in self.vocab:
                    ind.append(self.vocab[t])
                    data.append(c)
            ptr.append(len(ind))
        shape = (len(queries), len(self.vocab))
        qm = sparse.csr_matrix((np.array(data, dtype=np.float32), ind, ptr), shape=shape)
        return np.asarray((qm @ self.weights.T).todense())


def per_query(rankings: list[list[int]], gold: list[list[int]]) -> dict[str, np.ndarray]:
    ranks = []
    for ranked, g in zip(rankings, gold, strict=True):
        top = list(ranked[:TOP_K])
        hits = [top.index(x) + 1 for x in g if x in top]
        ranks.append(min(hits) if hits else 0)
    r = np.array(ranks)
    return {
        "hit@1": (r == 1).astype(float),
        "hit@5": ((r >= 1) & (r <= 5)).astype(float),
        "hit@10": (r >= 1).astype(float),
        "mrr@10": np.where(r > 0, 1.0 / np.maximum(r, 1), 0.0),
    }


def ci(values: np.ndarray, boot_idx: np.ndarray) -> dict[str, float]:
    means = values[boot_idx].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return {
        "mean": round(float(values.mean()), 4),
        "lo": round(float(lo), 4),
        "hi": round(float(hi), 4),
    }


t0 = time.perf_counter()
# fp16 only where it is faster: GTX 16-series cards have no tensor cores, and there the
# reranker ran 5 times slower in fp16 than in fp32 (2.1 against 10.2 pairs/s, 2026-11-10).
FP16 = os.environ.get("FP16", "auto")
use_fp16 = DEVICE == "cuda" and (
    FP16 == "1" or (FP16 == "auto" and "GTX 16" not in torch.cuda.get_device_name(0))
)
fp16 = {"torch_dtype": torch.float16} if use_fp16 else {}
log(f"fp16={use_fp16}")
distiluse = SentenceTransformer(
    "sentence-transformers/distiluse-base-multilingual-cased-v1", device=DEVICE
)
p_dist = encode(distiluse, passages, 64)
bge = SentenceTransformer("BAAI/bge-m3", device=DEVICE, model_kwargs=fp16)
bge.max_seq_length = 1024
p_bge = encode(bge, passages, 8)
bm25 = BM25(passages)
reranker = None
if not SKIP_RERANK:
    reranker = CrossEncoder(
        "BAAI/bge-reranker-v2-m3", max_length=512, device=DEVICE, model_kwargs=fp16
    )
timings["indexes_s"] = time.perf_counter() - t0
log("indexes done")

# ---------------------------------------------------------------- rank each question once
# The *_retrieval_needed sets are subsets of seen and blind, so each question is ranked
# once and each set picks its rows.
ranked: dict[str, dict[str, list[int]]] = {}  # arm -> question id -> ranking
near_dup: dict[str, bool] = {}
for kind in ("seen", "blind"):
    rows = query_sets[kind]
    if not rows:
        continue
    t0 = time.perf_counter()
    texts = [q["question"] for q in rows]
    arms: dict[str, list[list[int]]] = {}
    arms["2_distiluse_chunks"] = top_n(encode(distiluse, texts, 64) @ p_dist.T, TOP_K).tolist()
    q_bge = encode(bge, texts, 32)
    sims = q_bge @ p_bge.T
    for q, s in zip(rows, sims.max(axis=1), strict=True):
        near_dup[q["id"]] = bool(s >= NEAR_DUP)
    dense_top = top_n(sims, CANDIDATES).tolist()
    arms["3_bge_m3_chunks"] = [r[:TOP_K] for r in dense_top]
    bm25_top = top_n(bm25.scores(texts), CANDIDATES).tolist()
    arms["bm25_only"] = [r[:TOP_K] for r in bm25_top]
    fused = [rrf([d, s]) for d, s in zip(dense_top, bm25_top, strict=True)]
    arms["4_bge_m3_bm25_rrf"] = [f[:TOP_K] for f in fused]
    if reranker is not None:
        arm5 = []
        for q, f in zip(texts, fused, strict=True):
            cand = f[:RERANK_DEPTH]
            s = reranker.predict(
                [(q, passages[c]) for c in cand], batch_size=4, show_progress_bar=False
            )
            arm5.append([cand[i] for i in np.argsort(-np.asarray(s))][:TOP_K])
        arms["5_rrf_plus_bge_reranker_top20"] = arm5
    for arm, lists in arms.items():
        for q, r in zip(rows, lists, strict=True):
            ranked.setdefault(arm, {})[q["id"]] = r
    timings[f"{kind}_s"] = time.perf_counter() - t0
    log(f"{kind} ranked")

# ---------------------------------------------------------------- score each set
report: dict[str, Any] = {}
for set_name, rows in query_sets.items():
    if not rows:
        continue
    gold = [q["gold_chunks"] for q in rows]
    arms = {arm: [per_id[q["id"]] for q in rows] for arm, per_id in ranked.items()}
    leak_report[set_name]["near_duplicates"] = sum(near_dup[q["id"]] for q in rows)
    n = len(rows)
    boot = np.random.default_rng(SEED + 1).integers(0, n, size=(N_BOOT, n))
    metrics = {name: per_query(r, gold) for name, r in arms.items()}
    pairs = {
        "arm3_minus_arm2": ("3_bge_m3_chunks", "2_distiluse_chunks"),
        "arm4_minus_arm3": ("4_bge_m3_bm25_rrf", "3_bge_m3_chunks"),
        "arm4_minus_bm25": ("4_bge_m3_bm25_rrf", "bm25_only"),
    }
    if "5_rrf_plus_bge_reranker_top20" in metrics:
        pairs["arm5_minus_arm4"] = ("5_rrf_plus_bge_reranker_top20", "4_bge_m3_bm25_rrf")
    report[set_name] = {
        "n_queries": n,
        "mean_gold_chunks": round(float(np.mean([len(g) for g in gold])), 2),
        "arms": {a: {m: ci(v, boot) for m, v in ms.items()} for a, ms in metrics.items()},
        "paired": {
            label: {m: ci(metrics[a][m] - metrics[b][m], boot) for m in ("hit@1", "hit@5")}
            for label, (a, b) in pairs.items()
        },
    }

results = {
    "issue": 177,
    "book": "Việt Nam sử lược, Quyển I (Trần Trọng Kim), vi.wikisource",
    "n_chunks": len(passages),
    "questions_file": QUESTIONS.name,
    "generator": sorted({q["generator"] for q in questions}),
    "n_unanswerable": sum(q["kind"] == "unanswerable" for q in questions),
    "seed": SEED,
    "bootstrap": {"resamples": N_BOOT, "interval": "95% percentile"},
    "query_sets": report,
    "leakage": leak_report,
    "timings_s": {k: round(v, 1) for k, v in timings.items()},
    "total_s": round(time.perf_counter() - T_START, 1),
    "hardware": {
        "device": DEVICE,
        "gpu": torch.cuda.get_device_name(0) if DEVICE == "cuda" else None,
        "python": platform.python_version(),
        "torch": torch.__version__,
    },
}
(OUT / "results.json").write_text(
    json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
)
print(json.dumps({k: results[k] for k in ("query_sets", "leakage")}, indent=1, ensure_ascii=False))
