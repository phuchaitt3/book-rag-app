"""Why is the app's retrieval on the PDF below the in-memory benchmark? (#199)

The app (PDF, pgvector + Postgres full-text, evidence scoring) reaches 75.5% Hit@5 on the 208
blind questions; the benchmark (HTML chunks, in-memory cosine + BM25, gold-chunk scoring) reaches
89.4%. This script changes one thing at a time, on the same questions, with the same scoring:

  corpus    P = the PDF's 392 chunks (in Postgres, as the worker embedded them)
            H = the proofread HTML's 359 chunks (loaded into Postgres as a second book here)
  legs      dense_app  pgvector cosine over Ollama bge-m3 embeddings (the app's SQL)
            fts_app    Postgres to_tsvector('simple') + OR tsquery + ts_rank_cd (the app's SQL)
            dense_st   sentence-transformers bge-m3, in-memory cosine (the benchmark's)
            bm25       the benchmark's BM25
  fused     RRF k=60 over 30 candidates per leg, for the app pair, the benchmark pair, and both
            mixed pairs.
  scoring   a hit is a chunk in the top k whose text contains the question's evidence sentence
            (as experiments/e2e/retrieval_check.py does). On H the script also scores by the
            test set's gold chunk numbers, to measure the scoring factor itself.

Needs: Postgres from the Compose stack (DATABASE_URL), the PDF book in it (BOOK_ID), Ollama with
bge-m3, and sentence-transformers (see the run line). It writes
experiments/e2e/results/gap-199.json.

  BOOK_ID=<uuid> uv run --with sentence-transformers --with scipy --with torch \
    --index https://download.pytorch.org/whl/cu128 python experiments/e2e/gap.py
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

import asyncpg  # type: ignore[import-untyped]
import numpy as np
from retrieval_check import norm  # same letters-only normalisation as the app check
from scipy import sparse

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://bookrag:bookrag@localhost:5432/bookrag")
OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")
BOOK_ID = os.environ["BOOK_ID"]
QUESTIONS = ROOT / "experiments" / "book-testset" / "questions.jsonl"
HTML_CHUNKS = Path(
    os.environ.get(
        "HTML_CHUNKS", ROOT.parent / "main" / "experiments/book-testset/data/chunks.jsonl"
    )
)
CACHE = Path(os.environ.get("CACHE_DIR", HERE / "data" / "gap"))
OUT = HERE / "results" / "gap-199.json"
HTML_TITLE = "GAP-199 HTML chunks"
CANDIDATES, RRF_K, TOP = 30, 60, 10
WORD = re.compile(r"\w+", re.UNICODE)


def tokens(text: str) -> list[str]:
    return WORD.findall(text.lower())


def or_query(query: str) -> str:  # copy of book_rag_api.retrieval.or_query
    return " | ".join(WORD.findall(query))


def rrf(rankings: list[list[int]]) -> list[int]:  # book_rag.retrieval.fusion
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (RRF_K + rank)
    return [i for i, _ in sorted(scores.items(), key=lambda p: p[1], reverse=True)]


class BM25:  # the benchmark's (experiments/book-testset/bench.py)
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
        norm_ = k1 * (1 - b + b * dl / dl.mean())
        w = tf.tocoo()
        vals = w.data * (k1 + 1) / (w.data + norm_[w.row]) * idf[w.col]
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


def top_n(scores: np.ndarray, n: int) -> list[list[int]]:
    out = []
    for row in scores:
        order = np.argsort(-row, kind="stable")[:n]
        out.append([int(i) for i in order if row[i] > 0] if row.max() > 0 else [])
    return out


def ollama_embed(texts: list[str], batch: int = 16) -> list[list[float]]:
    vectors: list[list[float]] = []
    for i in range(0, len(texts), batch):
        body = json.dumps({"model": "bge-m3", "input": texts[i : i + batch]}).encode()
        req = urllib.request.Request(
            f"{OLLAMA}/api/embed", data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=600) as r:
            vectors += json.loads(r.read())["embeddings"]
    return vectors


def vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"


async def ensure_html_book(conn: Any, chunks: list[dict[str, Any]]) -> str:
    row = await conn.fetchrow("SELECT id FROM books WHERE title = $1", HTML_TITLE)
    if row:
        book_id = str(row["id"])
        n = await conn.fetchval(
            "SELECT count(embedding) FROM chunks WHERE book_id=$1::uuid", book_id
        )
        if n == len(chunks):
            return book_id
        await conn.execute("DELETE FROM books WHERE id=$1::uuid", book_id)
    book_id = str(
        await conn.fetchval(
            "INSERT INTO books (id, title) VALUES (gen_random_uuid(), $1) RETURNING id", HTML_TITLE
        )
    )
    vectors = ollama_embed([c["text"] for c in chunks])
    for i, (c, v) in enumerate(zip(chunks, vectors, strict=True)):
        await conn.execute(
            "INSERT INTO chunks (id, book_id, ordinal, text, embedding) "
            "VALUES (gen_random_uuid(),$1::uuid,$2,$3,$4::vector)",
            book_id,
            i,
            c["text"],
            vec(v),
        )
    return book_id


async def app_legs(
    conn: Any, book_id: str, queries: list[str], qvecs: list[list[float]], index: dict[str, int]
) -> tuple[list[list[int]], list[list[int]]]:
    """The app's two searches, with its own SQL, per question."""
    dense, fts = [], []
    for q, v in zip(queries, qvecs, strict=True):
        async with conn.transaction():
            await conn.execute("SET LOCAL hnsw.iterative_scan = strict_order")
            rows = await conn.fetch(
                "SELECT id FROM chunks WHERE book_id=$1::uuid AND embedding IS NOT NULL "
                "ORDER BY embedding <=> $2::vector LIMIT $3",
                book_id,
                vec(v),
                CANDIDATES,
            )
        dense.append([index[str(r["id"])] for r in rows])
        tsq = or_query(q)
        rows = (
            await conn.fetch(
                "SELECT id FROM chunks WHERE book_id=$1::uuid AND tsv @@ to_tsquery('simple',$2) "
                "ORDER BY ts_rank_cd(tsv, to_tsquery('simple',$2)) DESC LIMIT $3",
                book_id,
                tsq,
                CANDIDATES,
            )
            if tsq
            else []
        )
        fts.append([index[str(r["id"])] for r in rows])
    return dense, fts


async def fts_only(
    conn: Any, book_id: str, queries: list[str], index: dict[str, int], stop: set[str]
) -> list[list[int]]:
    """The app's full-text search with query words of `stop` left out (a probe, not the app)."""
    out = []
    for q in queries:
        tsq = " | ".join(w for w in WORD.findall(q) if w.lower() not in stop)
        rows = (
            await conn.fetch(
                "SELECT id FROM chunks WHERE book_id=$1::uuid AND tsv @@ to_tsquery('simple',$2) "
                "ORDER BY ts_rank_cd(tsv, to_tsquery('simple',$2)) DESC LIMIT $3",
                book_id,
                tsq,
                CANDIDATES,
            )
            if tsq
            else []
        )
        out.append([index[str(r["id"])] for r in rows])
    return out


def st_embed(texts: list[str], batch: int) -> np.ndarray:
    import torch
    from sentence_transformers import SentenceTransformer

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = SentenceTransformer("BAAI/bge-m3", device=device)
    model.max_seq_length = 1024
    out = model.encode(
        texts,
        batch_size=batch,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    ).astype(np.float32)
    del model
    if device == "cuda":
        torch.cuda.empty_cache()
    return out


def cached(name: str, make: Any) -> np.ndarray:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{name}.npy"
    if path.exists():
        return np.load(path)
    arr = np.asarray(make(), dtype=np.float32)
    np.save(path, arr)
    return arr


def interval(hits: list[int], seed: int = 199, reps: int = 5000) -> list[float]:
    rng = random.Random(seed)
    n = len(hits)
    means = sorted(sum(hits[rng.randrange(n)] for _ in range(n)) / n for _ in range(reps))
    return [round(100 * means[int(0.025 * reps)], 1), round(100 * means[int(0.975 * reps)], 1)]


def score(rankings: list[list[int]], gold: list[set[int]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in (1, 5):
        hits = [int(bool(set(r[:k]) & g)) for r, g in zip(rankings, gold, strict=True)]
        out[f"hit@{k}"] = round(100 * sum(hits) / len(hits), 1)
        out[f"hit@{k}_ci95"] = interval(hits)
        out[f"_hits{k}"] = hits
    return out


async def main() -> None:
    rows = [json.loads(x) for x in QUESTIONS.read_text(encoding="utf-8").splitlines() if x]
    rows = [r for r in rows if r["kind"] == "blind"]
    queries = [r["question"] for r in rows]
    html_text = await asyncio.to_thread(HTML_CHUNKS.read_text, encoding="utf-8")
    html = [json.loads(x) for x in html_text.splitlines()]
    conn = await asyncpg.connect(DATABASE_URL)
    html_book = await ensure_html_book(conn, html)
    pdf_rows = await conn.fetch(
        "SELECT id, text FROM chunks WHERE book_id=$1::uuid ORDER BY ordinal", BOOK_ID
    )
    html_rows = await conn.fetch(
        "SELECT id, text FROM chunks WHERE book_id=$1::uuid ORDER BY ordinal", html_book
    )
    corpora = {
        "P": (BOOK_ID, [str(r["id"]) for r in pdf_rows], [r["text"] for r in pdf_rows]),
        "H": (html_book, [str(r["id"]) for r in html_rows], [r["text"] for r in html_rows]),
    }
    assert [t for t in corpora["H"][2]] == [c["text"] for c in html], "HTML chunks differ from file"
    qvecs = cached("q_ollama", lambda: ollama_embed(queries))
    q_st = cached("q_st", lambda: st_embed(queries, 32))
    report: dict[str, Any] = {"questions": len(rows), "corpora": {}}
    for name, (book, ids, texts) in corpora.items():
        index = {cid: i for i, cid in enumerate(ids)}
        evidence = [norm(r["evidence"]) for r in rows]
        normed = [norm(t) for t in texts]
        gold = [{i for i, t in enumerate(normed) if e in t} for e in evidence]
        missing = sum(1 for g in gold if not g)
        keep = [i for i, g in enumerate(gold) if g]
        dense_app, fts_app = await app_legs(conn, book, queries, qvecs.tolist(), index)
        p_st = cached(f"p_st_{name}", lambda texts=texts: st_embed(texts, 8))
        dense_st = top_n(q_st @ p_st.T, CANDIDATES)
        bm25 = top_n(BM25(texts).scores(queries), CANDIDATES)
        legs = {"dense_app": dense_app, "dense_st": dense_st, "fts_app": fts_app, "bm25": bm25}
        arms = dict(legs)
        arms["fused_app (dense_app+fts_app)"] = [
            rrf([a, b]) for a, b in zip(dense_app, fts_app, strict=True)
        ]
        arms["fused_bench (dense_st+bm25)"] = [
            rrf([a, b]) for a, b in zip(dense_st, bm25, strict=True)
        ]
        arms["dense_app+bm25"] = [rrf([a, b]) for a, b in zip(dense_app, bm25, strict=True)]
        arms["dense_st+fts_app"] = [rrf([a, b]) for a, b in zip(dense_st, fts_app, strict=True)]
        # Probe: the same full-text search without the words found in more than DF of the chunks.
        n_chunks = len(texts)
        df_count = Counter(w for t in texts for w in set(tokens(t)))
        for share in (0.20, 0.05):
            stop = {w for w, c in df_count.items() if c > share * n_chunks}
            leg = await fts_only(conn, book, queries, index, stop)
            arms[f"fts_app minus words in >{int(share * 100)}% of chunks"] = leg
            arms[f"dense_app + fts_app minus >{int(share * 100)}%"] = [
                rrf([a, b]) for a, b in zip(dense_app, leg, strict=True)
            ]
        res: dict[str, Any] = {
            "chunks": len(texts),
            "evidence_not_in_one_chunk": missing,
            "arms": {},
        }
        for arm, ranked in arms.items():
            res["arms"][arm] = score([ranked[i] for i in keep], [gold[i] for i in keep])
        if name == "H":  # the scoring factor: the test set's gold chunk numbers
            gold_n = [set(r["gold_chunks"]) for r in rows]
            res["gold_chunk_scoring"] = {arm: score(ranked, gold_n) for arm, ranked in arms.items()}
            res["evidence_vs_gold_same_chunks"] = sum(
                g == gn for g, gn in zip(gold, gold_n, strict=True)
            )
        res["scored"] = len(keep)
        report["corpora"][name] = res
    await conn.close()
    P, H = report["corpora"]["P"], report["corpora"]["H"]
    assert P["scored"] == H["scored"] == len(rows), "paired comparison needs all questions scored"
    fa, fb = "fused_app (dense_app+fts_app)", "fused_bench (dense_st+bm25)"
    comparisons = {
        "H bench - H app (search, on HTML)": (H["arms"][fb], H["arms"][fa]),
        "P bench - P app (search, on PDF)": (P["arms"][fb], P["arms"][fa]),
        "H bench - P bench (text, bench search)": (H["arms"][fb], P["arms"][fb]),
        "H app - P app (text, app search)": (H["arms"][fa], P["arms"][fa]),
        "P dense_st+bm25 - P dense_app+bm25 (dense leg)": (
            P["arms"][fb],
            P["arms"]["dense_app+bm25"],
        ),
        "P dense_app+bm25 - P app (lexical leg)": (P["arms"]["dense_app+bm25"], P["arms"][fa]),
        "H dense_app+bm25 - H app (lexical leg)": (H["arms"]["dense_app+bm25"], H["arms"][fa]),
        "P dense_app alone - P app (does fusion help the app?)": (
            P["arms"]["dense_app"],
            P["arms"][fa],
        ),
    }
    paired: dict[str, Any] = {}
    for label, (a, b) in comparisons.items():
        diff = [x - y for x, y in zip(a["_hits5"], b["_hits5"], strict=True)]
        mean = 100 * sum(diff) / len(diff)
        rng = random.Random(199)
        means = sorted(
            100 * sum(diff[rng.randrange(len(diff))] for _ in diff) / len(diff) for _ in range(5000)
        )
        paired[label] = {
            "hit@5_diff": round(mean, 1),
            "ci95": [round(means[125], 1), round(means[4875], 1)],
        }
    report["paired_hit@5"] = paired
    for res in report["corpora"].values():  # keep the file small: drop per-question hit lists
        for block in (res["arms"], res.get("gold_chunk_scoring", {})):
            for m in block.values():
                m.pop("_hits1", None), m.pop("_hits5", None)
    OUT.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print("\npaired Hit@5 differences (points, 95% bootstrap):")
    for label, d in paired.items():
        print(f"  {label:58s} {d['hit@5_diff']:+5.1f}  {d['ci95']}")
    for name, res in report["corpora"].items():
        print(f"\ncorpus {name}: {res['chunks']} chunks, scored {res['scored']}")
        for arm, m in res["arms"].items():
            print(
                f"  {arm:32s} Hit@1 {m['hit@1']:5.1f}  Hit@5 {m['hit@5']:5.1f}  {m['hit@5_ci95']}"
            )
        if "gold_chunk_scoring" in res:
            print("  -- same arms scored by gold chunk numbers")
            for arm, m in res["gold_chunk_scoring"].items():
                print(f"  {arm:32s} Hit@1 {m['hit@1']:5.1f}  Hit@5 {m['hit@5']:5.1f}")


if __name__ == "__main__":
    asyncio.run(main())
