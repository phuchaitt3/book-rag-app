"""Retrieval benchmark on UIT-ViQuAD2.0: the v1 design against the v2 design (issue #171).

Runs as a Kaggle script kernel (GPU, internet on); see README.md next to this file.
It downloads the dataset and models at run time and writes only numbers to
results.json: no dataset text leaves the kernel.

Arms (retrieval only, no LLM):
  1 v1: distiluse-base-multilingual-cased-v1 over a question index; the held-out
    questions are removed from the index and a hit returns that question's passage.
  2 distiluse over passages.
  3 bge-m3 over passages.
  4 bge-m3 + BM25 fused with reciprocal rank fusion, k=60, 30 candidates per list
    (as packages/rag/src/book_rag/retrieval/hybrid.py does).
  5 arm 4 + bge-reranker-v2-m3 over the fused top 20.
"""

import json
import os
import platform
import re
import time
from collections import Counter

import numpy as np
import torch
from datasets import load_dataset
from scipy import sparse
from sentence_transformers import CrossEncoder, SentenceTransformer

SEED = 171
N_QUERIES = 1000
TOP_K = 10
CANDIDATES = 30  # per search path before fusion, as HybridRetriever's default
RRF_K = 60  # as book_rag.retrieval.fusion.RRF_K
RERANK_DEPTH = 20
N_BOOT = 2000
SKIP_RERANK = os.environ.get("SKIP_RERANK") == "1"
OUT = os.environ.get("OUT_DIR", "/kaggle/working")

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
T_START = time.perf_counter()
timings: dict[str, float] = {}


def log(msg: str) -> None:
    print(f"[{time.perf_counter() - T_START:7.1f}s] {msg}", flush=True)


# ---------------------------------------------------------------- data
log(f"device={DEVICE} gpu={torch.cuda.get_device_name(0) if DEVICE == 'cuda' else '-'}")
ds = load_dataset("taidng/UIT-ViQuAD2.0")
split_sizes = {name: len(ds[name]) for name in ds}
log(f"splits {split_sizes}")
train = ds["train"]


def answerable(row: dict) -> bool:
    if "is_impossible" in row and row["is_impossible"] is not None:
        return not bool(row["is_impossible"])
    return bool(row["answers"]["text"])


rows = [r for r in train if answerable(r)]
passage_ids: dict[str, int] = {}
passages: list[str] = []
questions: list[str] = []
gold: list[int] = []
for r in rows:
    ctx = r["context"]
    if ctx not in passage_ids:
        passage_ids[ctx] = len(passages)
        passages.append(ctx)
    questions.append(r["question"])
    gold.append(passage_ids[ctx])
gold_arr = np.array(gold)
log(f"answerable questions={len(questions)} passages={len(passages)}")

rng = np.random.default_rng(SEED)
query_idx = np.sort(rng.choice(len(questions), size=N_QUERIES, replace=False))
query_gold = gold_arr[query_idx]
query_texts = [questions[i] for i in query_idx]
index_mask = np.ones(len(questions), dtype=bool)
index_mask[query_idx] = False
# Passages that keep at least one question in arm 1's index: the rest cannot be found.
reachable = set(gold_arr[index_mask].tolist())
arm1_reachable = float(np.mean([g in reachable for g in query_gold]))


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


def bm25_scores(docs: list[str], queries: list[str], k1: float = 1.2, b: float = 0.75):
    vocab: dict[str, int] = {}
    data, ind, ptr, lengths = [], [], [0], []
    for d in docs:
        counts = Counter(tokens(d))
        lengths.append(sum(counts.values()))
        for t, c in counts.items():
            ind.append(vocab.setdefault(t, len(vocab)))
            data.append(c)
        ptr.append(len(ind))
    tf = sparse.csr_matrix(
        (np.array(data, dtype=np.float32), ind, ptr), shape=(len(docs), len(vocab))
    )
    dl = np.array(lengths, dtype=np.float32)
    df = np.bincount(tf.indices, minlength=len(vocab))
    idf = np.log(1 + (len(docs) - df + 0.5) / (df + 0.5)).astype(np.float32)
    norm = k1 * (1 - b + b * dl / dl.mean())
    w = tf.tocoo()
    vals = w.data * (k1 + 1) / (w.data + norm[w.row]) * idf[w.col]
    weights = sparse.csr_matrix((vals, (w.row, w.col)), shape=tf.shape)
    q_data, q_ind, q_ptr = [], [], [0]
    for q in queries:
        for t, c in Counter(tokens(q)).items():
            if t in vocab:
                q_ind.append(vocab[t])
                q_data.append(c)
        q_ptr.append(len(q_ind))
    qm = sparse.csr_matrix(
        (np.array(q_data, dtype=np.float32), q_ind, q_ptr), shape=(len(queries), len(vocab))
    )
    return np.asarray((qm @ weights.T).todense())


def per_query(rankings: list[list[int]]) -> dict[str, np.ndarray]:
    ranks = []
    for ranked, g in zip(rankings, query_gold, strict=True):
        ranked = ranked[:TOP_K]
        ranks.append(ranked.index(g) + 1 if g in ranked else 0)
    r = np.array(ranks)
    return {
        "hit@1": (r == 1).astype(float),
        "hit@5": ((r >= 1) & (r <= 5)).astype(float),
        "hit@10": (r >= 1).astype(float),
        "mrr@10": np.where(r > 0, 1.0 / np.maximum(r, 1), 0.0),
    }


boot_idx = np.random.default_rng(SEED + 1).integers(0, N_QUERIES, size=(N_BOOT, N_QUERIES))


def ci(values: np.ndarray) -> dict[str, float]:
    means = values[boot_idx].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return {
        "mean": round(float(values.mean()), 4),
        "lo": round(float(lo), 4),
        "hi": round(float(hi), 4),
    }


arms: dict[str, list[list[int]]] = {}

# ---------------------------------------------------------------- arms 1 and 2: distiluse
t0 = time.perf_counter()
distiluse = SentenceTransformer(
    "sentence-transformers/distiluse-base-multilingual-cased-v1", device=DEVICE
)
q_all = encode(distiluse, questions, 256)
q_emb = q_all[query_idx]
idx_rows = np.flatnonzero(index_mask)
sims = q_emb @ q_all[idx_rows].T
top_q = top_n(sims, 200)
arm1 = []
for row in top_q:
    seen: list[int] = []
    for j in row:
        p = int(gold_arr[idx_rows[j]])
        if p not in seen:
            seen.append(p)
            if len(seen) == TOP_K:
                break
    arm1.append(seen)
arms["1_v1_distiluse_question_index"] = arm1
timings["arm1_s"] = time.perf_counter() - t0
log("arm 1 done")

t0 = time.perf_counter()
p_dist = encode(distiluse, passages, 128)
arms["2_distiluse_passages"] = top_n(q_emb @ p_dist.T, TOP_K).tolist()
timings["arm2_s"] = time.perf_counter() - t0
del distiluse
log("arm 2 done")

# ---------------------------------------------------------------- arms 3 and 4: bge-m3 (+ BM25)
t0 = time.perf_counter()
bge = SentenceTransformer(
    "BAAI/bge-m3",
    device=DEVICE,
    model_kwargs={"torch_dtype": torch.float16} if DEVICE == "cuda" else {},
)
bge.max_seq_length = 1024
p_bge = encode(bge, passages, 16)
q_bge = encode(bge, query_texts, 64)
dense_scores = q_bge @ p_bge.T
dense_top = top_n(dense_scores, CANDIDATES).tolist()
arms["3_bge_m3_passages"] = [r[:TOP_K] for r in dense_top]
timings["arm3_s"] = time.perf_counter() - t0
del bge
log("arm 3 done")

t0 = time.perf_counter()
bm25_top = top_n(bm25_scores(passages, query_texts), CANDIDATES).tolist()
fused = [rrf([d, s]) for d, s in zip(dense_top, bm25_top, strict=True)]
arms["4_bge_m3_bm25_rrf"] = [f[:TOP_K] for f in fused]
arms["bm25_only"] = [r[:TOP_K] for r in bm25_top]
timings["arm4_extra_s"] = time.perf_counter() - t0
log("arm 4 done")

# ---------------------------------------------------------------- arm 5: reranker
if not SKIP_RERANK:
    t0 = time.perf_counter()
    reranker = CrossEncoder(
        "BAAI/bge-reranker-v2-m3",
        max_length=512,
        device=DEVICE,
        model_kwargs={"torch_dtype": torch.float16} if DEVICE == "cuda" else {},
    )
    arm5 = []
    for q, f in zip(query_texts, fused, strict=True):
        cand = f[:RERANK_DEPTH]
        s = reranker.predict(
            [(q, passages[c]) for c in cand], batch_size=RERANK_DEPTH, show_progress_bar=False
        )
        arm5.append([cand[i] for i in np.argsort(-np.asarray(s))][:TOP_K])
    arms["5_rrf_plus_bge_reranker_top20"] = arm5
    timings["arm5_s"] = time.perf_counter() - t0
    log("arm 5 done")

# ---------------------------------------------------------------- report
metrics = {name: per_query(r) for name, r in arms.items()}
report = {name: {m: ci(v) for m, v in ms.items()} for name, ms in metrics.items()}
a1, a4 = metrics["1_v1_distiluse_question_index"], metrics["4_bge_m3_bm25_rrf"]
paired = {m: ci(a4[m] - a1[m]) for m in ("hit@1", "hit@5", "mrr@10")}
results = {
    "issue": 171,
    "dataset": "taidng/UIT-ViQuAD2.0, train split, answerable rows",
    "split_sizes": split_sizes,
    "n_questions": len(questions),
    "n_passages": len(passages),
    "n_queries": N_QUERIES,
    "seed": SEED,
    "bootstrap": {"resamples": N_BOOT, "interval": "95% percentile"},
    "arm1_gold_passage_reachable": round(arm1_reachable, 4),
    "arms": report,
    "arm4_minus_arm1_paired": paired,
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
