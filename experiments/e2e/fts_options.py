"""Options for the app's full-text leg, measured one at a time on the #199 harness (#204).

Reuses gap.py (same 208 blind questions, same corpora, same scoring, same RRF) and swaps only
the lexical leg that is fused with the app's pgvector dense leg:

  fts_app        the app today: OR to_tsquery + ts_rank_cd
  bm25_sql       BM25 computed in Postgres from the tsvector (document frequency and length of
                 the book taken on the fly): no new table, no extension
  bm25_py        the benchmark's BM25 in memory (the ceiling; gap.py's `bm25`)
  fts_minus_N    fts_app with query words found in more than N% of the book's chunks dropped
  ts_rank_norm   fts_app with ts_rank_cd's length normalisation flags (1, 2, 32)

It also times each Postgres leg per query (median and p95 over the 208 questions, warm).

  BOOK_ID=<uuid> uv run --with scipy python experiments/e2e/fts_options.py
Writes experiments/e2e/results/fts-options-204.json.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from collections import Counter
from typing import Any

import asyncpg  # type: ignore[import-untyped]
import gap
from gap import (
    BM25,
    CANDIDATES,
    DATABASE_URL,
    QUESTIONS,
    WORD,
    app_legs,
    cached,
    norm,
    ollama_embed,
    or_query,
    rrf,
    score,
    tokens,
    top_n,
)

K1, B = 1.2, 0.75

BM25_SQL = """
WITH q AS (
  SELECT lexeme AS term, cardinality(positions) AS qtf FROM unnest(to_tsvector('simple', $2))
), docs AS (
  SELECT c.id, c.tsv, (SELECT coalesce(sum(cardinality(positions)), 0) FROM unnest(c.tsv)) AS dl
  FROM chunks c WHERE c.book_id = $1::uuid
), stats AS (
  SELECT count(*)::float AS n, avg(dl)::float AS avgdl FROM docs
), df AS (
  SELECT u.lexeme AS term, count(*)::float AS df
  FROM docs d, unnest(d.tsv) u WHERE u.lexeme IN (SELECT term FROM q) GROUP BY 1
)
SELECT d.id
FROM docs d, unnest(d.tsv) u
JOIN q ON q.term = u.lexeme
JOIN df ON df.term = u.lexeme, stats s
WHERE d.tsv @@ to_tsquery('simple', $3)
GROUP BY d.id, d.dl, s.avgdl, s.n
ORDER BY sum(q.qtf * ln(1 + (s.n - df.df + 0.5) / (df.df + 0.5))
             * cardinality(u.positions) * ($4 + 1)
             / (cardinality(u.positions) + $4 * (1 - $5 + $5 * d.dl / s.avgdl))) DESC
LIMIT $6
"""

# The same, but query terms found in more than half of the book's chunks are dropped (their
# idf is near zero) so the GIN-matched candidate set is not "every chunk".
BM25_SQL_PRUNED = BM25_SQL.replace(
    "WHERE u.lexeme IN (SELECT term FROM q) GROUP BY 1",
    "WHERE u.lexeme IN (SELECT term FROM q) GROUP BY 1 "
    "HAVING count(*) <= 0.5 * (SELECT count(*) FROM docs)",
).replace("WHERE d.tsv @@ to_tsquery('simple', $3)", "WHERE $3 <> ''")


async def sql_leg(
    conn: Any, book: str, queries: list[str], index: dict[str, int], sql: str, args: Any
) -> tuple[list[list[int]], list[float]]:
    out, times = [], []
    for q in queries:
        tsq = or_query(q)
        t0 = time.perf_counter()
        rows = await conn.fetch(sql, *args(book, q, tsq)) if tsq else []
        times.append((time.perf_counter() - t0) * 1000)
        out.append([index[str(r["id"])] for r in rows])
    return out, times


def lat(times: list[float]) -> dict[str, float]:
    s = sorted(times)
    return {"median_ms": round(statistics.median(s), 2), "p95_ms": round(s[int(0.95 * len(s))], 2)}


async def main() -> None:
    rows = [json.loads(x) for x in QUESTIONS.read_text(encoding="utf-8").splitlines() if x]
    rows = [r for r in rows if r["kind"] == "blind"]
    queries = [r["question"] for r in rows]
    conn = await asyncpg.connect(DATABASE_URL)
    html_book = str(await conn.fetchval("SELECT id FROM books WHERE title=$1", gap.HTML_TITLE))
    qvecs = cached("q_ollama", lambda: ollama_embed(queries))
    report: dict[str, Any] = {"questions": len(rows), "corpora": {}}
    for name, book in (("P", gap.BOOK_ID), ("H", html_book)):
        recs = await conn.fetch(
            "SELECT id, text FROM chunks WHERE book_id=$1::uuid ORDER BY ordinal", book
        )
        ids = [str(r["id"]) for r in recs]
        texts = [r["text"] for r in recs]
        index = {c: i for i, c in enumerate(ids)}
        normed = [norm(t) for t in texts]
        gold = [{i for i, t in enumerate(normed) if norm(r["evidence"]) in t} for r in rows]
        assert all(gold), "every question needs evidence in one chunk"
        dense, fts = await app_legs(conn, book, queries, qvecs.tolist(), index)
        legs: dict[str, list[list[int]]] = {"fts_app": fts}
        timing: dict[str, Any] = {}
        legs["bm25_py"] = top_n(BM25(texts).scores(queries), CANDIDATES)
        legs["bm25_sql"], t = await sql_leg(
            conn, book, queries, index, BM25_SQL, lambda b, q, s: (b, q, s, K1, B, CANDIDATES)
        )
        timing["bm25_sql"] = lat(t)
        legs["bm25_sql_pruned"], t = await sql_leg(
            conn,
            book,
            queries,
            index,
            BM25_SQL_PRUNED,
            lambda b, q, s: (b, q, s, K1, B, CANDIDATES),
        )
        timing["bm25_sql_pruned"] = lat(t)
        # fts_app timing, and ts_rank_cd with length normalisation flags
        base = (
            "SELECT id FROM chunks WHERE book_id=$1::uuid AND tsv @@ to_tsquery('simple',$2) "
            "ORDER BY ts_rank_cd(tsv, to_tsquery('simple',$2){flag}) DESC LIMIT $3"
        )
        for label, flag in (("fts_app", ""), ("ts_rank_norm1", ", 1"), ("ts_rank_norm2", ", 2")):
            leg, t = await sql_leg(
                conn,
                book,
                queries,
                index,
                base.format(flag=flag),
                lambda b, q, s: (b, s, CANDIDATES),
            )
            legs[label] = leg
            timing[label] = lat(t)
        n = len(texts)
        df = Counter(w for t in texts for w in set(tokens(t)))
        for share in (0.5, 0.2, 0.1, 0.05):
            stop = {w for w, c in df.items() if c > share * n}
            qs = [" ".join(w for w in WORD.findall(q) if w.lower() not in stop) for q in queries]
            leg, _ = await sql_leg(
                conn, book, qs, index, base.format(flag=""), lambda b, q, s: (b, s, CANDIDATES)
            )
            legs[f"fts_minus_{int(share * 100)}pct"] = leg
        arms: dict[str, list[list[int]]] = {"dense_app": dense}
        arms.update({f"leg: {k}": v for k, v in legs.items()})
        for k, v in legs.items():
            arms[f"fused: dense_app + {k}"] = [rrf([a, b]) for a, b in zip(dense, v, strict=True)]
        res = {a: score(r, gold) for a, r in arms.items()}
        # sql vs python: how many questions the two BM25 rankings agree on in the top 5
        same = sum(legs["bm25_sql"][i][:5] == legs["bm25_py"][i][:5] for i in range(len(queries)))
        for m in res.values():
            m.pop("_hits1"), m.pop("_hits5")
        report["corpora"][name] = {
            "chunks": n,
            "arms": res,
            "latency": timing,
            "bm25_sql_top5_equals_py": same,
        }
        print(f"\ncorpus {name}: {n} chunks; bm25_sql top5 == bm25_py on {same}/{len(queries)}")
        for a, m in res.items():
            print(f"  {a:42s} Hit@1 {m['hit@1']:5.1f}  Hit@5 {m['hit@5']:5.1f}  {m['hit@5_ci95']}")
        print("  latency", timing)
    await conn.close()
    (gap.HERE / "results" / "fts-options-204.json").write_text(
        json.dumps(report, indent=1), encoding="utf-8"
    )


if __name__ == "__main__":
    asyncio.run(main())
