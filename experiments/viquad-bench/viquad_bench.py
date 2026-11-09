"""Retrieval benchmark on UIT-ViQuAD2.0: the v1 design against the v2 design (#171, #173).

Runs as a Kaggle script kernel (GPU, internet on); see README.md next to this file.
It downloads the dataset, v1's question files and the models at run time and writes
only numbers to results.json: no dataset text leaves the kernel.

Arms (retrieval only, no LLM):
  1 v1: distiluse-base-multilingual-cased-v1 over a question index; a hit returns that
    question's passage.
  2 distiluse over passages.
  3 bge-m3 over passages.
  4 bge-m3 + BM25 fused with reciprocal rank fusion, k=60, 30 candidates per list
    (as packages/rag/src/book_rag/retrieval/hybrid.py does).
  5 arm 4 + bge-reranker-v2-m3 over the fused top 20.

Query sets:
  heldout_1000  1,000 dataset questions (seed 171), all removed from arm 1's index (#171).
  v1_reworded_within_context, v1_reworded_without_context  v1's two sets of 100 questions
    rewritten by gpt-4o-mini, with and without the passage shown (#173). Arm 1 runs twice:
    with the original questions left in its index, as v1 ran it, and with them removed.
"""

import json
import os
import platform
import re
import time
from collections import Counter
from typing import Any

import numpy as np
import pandas as pd
import torch
from datasets import load_dataset
from scipy import sparse
from sentence_transformers import CrossEncoder, SentenceTransformer

SEED = 171
N_HELDOUT = 1000
TOP_K = 10
CANDIDATES = 30  # per search path before fusion, as HybridRetriever's default
RRF_K = 60  # as book_rag.retrieval.fusion.RRF_K
RERANK_DEPTH = 20
N_BOOT = 2000
SKIP_RERANK = os.environ.get("SKIP_RERANK") == "1"
OUT = os.environ.get("OUT_DIR", "/kaggle/working")
V1_EVAL = (
    "https://raw.githubusercontent.com/phuchaitt3/book-rag/HEAD/Source_Code/Evaluation/"
    "100_samples_similar_{kind}/input_files/queries_100_uniques_similar_dataset_{kind}.xlsx"
)
V1_SETS = {
    "v1_reworded_within_context": "within_context",
    "v1_reworded_without_context": "without_context",
}

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
T_START = time.perf_counter()
timings: dict[str, float] = {}


def log(msg: str) -> None:
    print(f"[{time.perf_counter() - T_START:7.1f}s] {msg}", flush=True)


# ---------------------------------------------------------------- corpus
log(f"device={DEVICE} gpu={torch.cuda.get_device_name(0) if DEVICE == 'cuda' else '-'}")
ds = load_dataset("taidng/UIT-ViQuAD2.0")
split_sizes = {name: len(ds[name]) for name in ds}
log(f"splits {split_sizes}")


def answerable(row: dict[str, Any]) -> bool:
    if "is_impossible" in row and row["is_impossible"] is not None:
        return not bool(row["is_impossible"])
    return bool(row["answers"]["text"])


passage_ids: dict[str, int] = {}
passages: list[str] = []
questions: list[str] = []
gold: list[int] = []
for r in ds["train"]:
    if not answerable(r):
        continue
    ctx = r["context"]
    if ctx not in passage_ids:
        passage_ids[ctx] = len(passages)
        passages.append(ctx)
    questions.append(r["question"])
    gold.append(passage_ids[ctx])
gold_arr = np.array(gold)
log(f"answerable questions={len(questions)} passages={len(passages)}")
question_rows: dict[tuple[str, int], list[int]] = {}
for i, (q, g) in enumerate(zip(questions, gold, strict=True)):
    question_rows.setdefault((q.strip(), g), []).append(i)


# ---------------------------------------------------------------- query sets
query_sets: dict[str, dict[str, Any]] = {}

rng = np.random.default_rng(SEED)
held = np.sort(rng.choice(len(questions), size=N_HELDOUT, replace=False))
query_sets["heldout_1000"] = {
    "texts": [questions[i] for i in held],
    "gold": gold_arr[held],
    "arm1_variants": {"1_v1_distiluse_question_index": held},
}

for name, kind in V1_SETS.items():
    df = pd.read_excel(V1_EVAL.format(kind=kind))
    original_col = f"original_question_{kind}"
    texts, golds, originals, unmatched = [], [], [], 0
    for ctx, q, orig in zip(df["context"], df["question"], df[original_col], strict=True):
        pid = passage_ids.get(ctx, passage_ids.get(str(ctx).strip()))
        if pid is None:
            unmatched += 1
            continue
        texts.append(str(q).strip())
        golds.append(pid)
        originals += question_rows.get((str(orig).strip(), pid), [])
    query_sets[name] = {
        "texts": texts,
        "gold": np.array(golds),
        "arm1_variants": {
            "1_v1_index_keeps_originals": np.array([], dtype=int),
            "1_v1_originals_removed": np.array(sorted(set(originals)), dtype=int),
        },
        "unmatched_passages": unmatched,
        "originals_found": len(set(originals)),
    }
    log(f"{name}: {len(texts)} queries, {unmatched} unmatched, {len(set(originals))} originals")


# ---------------------------------------------------------------- helpers
def encode(model: SentenceTransformer, texts: list[str], batch: int) -> np.ndarray:
    return model.encode(
        texts,
        batch_size=batch,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    ).astype(np.float32)


def top_n(scores: np.ndarray, n: int) -> np.ndarray:
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


TOKEN = re.compile(r"\w+", re.UNICODE)


def tokens(text: str) -> list[str]:
    # Close to Postgres to_tsvector('simple', ...): lowercase words, no stemming.
    return TOKEN.findall(text.lower())


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


def per_query(rankings: list[list[int]], gold_ids: np.ndarray) -> dict[str, np.ndarray]:
    ranks = []
    for ranked, g in zip(rankings, gold_ids, strict=True):
        top = list(ranked[:TOP_K])
        ranks.append(top.index(g) + 1 if g in top else 0)
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


# ---------------------------------------------------------------- indexes (built once)
t0 = time.perf_counter()
distiluse = SentenceTransformer(
    "sentence-transformers/distiluse-base-multilingual-cased-v1", device=DEVICE
)
q_index = encode(distiluse, questions, 256)
p_dist = encode(distiluse, passages, 128)
timings["distiluse_index_s"] = time.perf_counter() - t0
log("distiluse indexes done")

t0 = time.perf_counter()
fp16 = {"torch_dtype": torch.float16} if DEVICE == "cuda" else {}
bge = SentenceTransformer("BAAI/bge-m3", device=DEVICE, model_kwargs=fp16)
bge.max_seq_length = 1024
p_bge = encode(bge, passages, 16)
timings["bge_m3_index_s"] = time.perf_counter() - t0
log("bge-m3 index done")

t0 = time.perf_counter()
bm25 = BM25(passages)
timings["bm25_index_s"] = time.perf_counter() - t0

reranker = None
if not SKIP_RERANK:
    reranker = CrossEncoder(
        "BAAI/bge-reranker-v2-m3", max_length=512, device=DEVICE, model_kwargs=fp16
    )


def arm1(q_emb: np.ndarray, excluded: np.ndarray) -> list[list[int]]:
    keep = np.ones(len(questions), dtype=bool)
    keep[excluded] = False
    rows = np.flatnonzero(keep)
    out = []
    for row in top_n(q_emb @ q_index[rows].T, 200):
        seen: list[int] = []
        for j in row:
            p = int(gold_arr[rows[j]])
            if p not in seen:
                seen.append(p)
                if len(seen) == TOP_K:
                    break
        out.append(seen)
    return out


# ---------------------------------------------------------------- evaluate each set
report: dict[str, Any] = {}
for set_name, qs in query_sets.items():
    t0 = time.perf_counter()
    texts, set_gold = qs["texts"], qs["gold"]
    arms: dict[str, list[list[int]]] = {}
    q_dist = encode(distiluse, texts, 256)
    for arm_name, excluded in qs["arm1_variants"].items():
        arms[arm_name] = arm1(q_dist, excluded)
    arms["2_distiluse_passages"] = top_n(q_dist @ p_dist.T, TOP_K).tolist()
    dense_top = top_n(encode(bge, texts, 64) @ p_bge.T, CANDIDATES).tolist()
    arms["3_bge_m3_passages"] = [r[:TOP_K] for r in dense_top]
    bm25_top = top_n(bm25.scores(texts), CANDIDATES).tolist()
    arms["bm25_only"] = [r[:TOP_K] for r in bm25_top]
    fused = [rrf([d, s]) for d, s in zip(dense_top, bm25_top, strict=True)]
    arms["4_bge_m3_bm25_rrf"] = [f[:TOP_K] for f in fused]
    timings[f"{set_name}_arms1to4_s"] = time.perf_counter() - t0
    if reranker is not None:
        t0 = time.perf_counter()
        arm5 = []
        for q, f in zip(texts, fused, strict=True):
            cand = f[:RERANK_DEPTH]
            s = reranker.predict(
                [(q, passages[c]) for c in cand],
                batch_size=RERANK_DEPTH,
                show_progress_bar=False,
            )
            arm5.append([cand[i] for i in np.argsort(-np.asarray(s))][:TOP_K])
        arms["5_rrf_plus_bge_reranker_top20"] = arm5
        timings[f"{set_name}_arm5_s"] = time.perf_counter() - t0

    n = len(texts)
    boot = np.random.default_rng(SEED + 1).integers(0, n, size=(N_BOOT, n))
    metrics = {name: per_query(r, set_gold) for name, r in arms.items()}
    first_arm1 = next(iter(qs["arm1_variants"]))
    pairs = {
        "arm4_minus_" + first_arm1: ("4_bge_m3_bm25_rrf", first_arm1),
        "arm4_minus_arm3": ("4_bge_m3_bm25_rrf", "3_bge_m3_passages"),
        "arm4_minus_bm25": ("4_bge_m3_bm25_rrf", "bm25_only"),
    }
    if "5_rrf_plus_bge_reranker_top20" in metrics:
        pairs["arm5_minus_arm4"] = ("5_rrf_plus_bge_reranker_top20", "4_bge_m3_bm25_rrf")
    report[set_name] = {
        "n_queries": n,
        **{k: v for k, v in qs.items() if k in ("unmatched_passages", "originals_found")},
        "arms": {a: {m: ci(v, boot) for m, v in ms.items()} for a, ms in metrics.items()},
        "paired": {
            label: {m: ci(metrics[a][m] - metrics[b][m], boot) for m in ("hit@1", "hit@5")}
            for label, (a, b) in pairs.items()
        },
    }
    log(f"{set_name} done")

results = {
    "issues": [171, 173],
    "dataset": "taidng/UIT-ViQuAD2.0, train split, answerable rows",
    "split_sizes": split_sizes,
    "n_questions": len(questions),
    "n_passages": len(passages),
    "seed": SEED,
    "bootstrap": {"resamples": N_BOOT, "interval": "95% percentile"},
    "query_sets": report,
    "timings_s": {k: round(v, 1) for k, v in timings.items()},
    "total_s": round(time.perf_counter() - T_START, 1),
    "hardware": {
        "device": DEVICE,
        "gpu": torch.cuda.get_device_name(0) if DEVICE == "cuda" else None,
        "python": platform.python_version(),
        "torch": torch.__version__,
    },
}
with open(os.path.join(OUT, "results.json"), "w", encoding="utf-8") as fh:
    json.dump(results, fh, indent=2)
print(json.dumps(results, indent=2))
