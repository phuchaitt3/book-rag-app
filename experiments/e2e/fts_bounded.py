"""BM25 in Postgres with a bounded candidate set, stored statistics, timed and scored (#208).

fts_options.py (#204) scores every chunk that matches any query word, about 80 ms per question
on 392 chunks. Here the statistics are stored (`tmp_chunk_len`, `tmp_book_terms`, created and
dropped by this script) and the candidates are the chunks the GIN index finds for the query's
*rare* words only (a word is rare when it is in at most SHARE of the book's chunks). BM25 then
scores those chunks over all query words. SHARE is swept; 1.0 means no bound.

  BOOK_ID=<uuid> uv run --with scipy python experiments/e2e/fts_bounded.py
Writes experiments/e2e/results/fts-bounded-208.json.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import asyncpg  # type: ignore[import-untyped]
import gap
from fts_options import K1, B, lat, sql_leg
from gap import (
    CANDIDATES,
    DATABASE_URL,
    QUESTIONS,
    app_legs,
    cached,
    norm,
    ollama_embed,
    rrf,
    score,
)

SQL = """
WITH q AS (
  SELECT lexeme AS term, cardinality(positions) AS qtf FROM unnest(to_tsvector('simple', $2))
), s AS (
  SELECT count(*)::float AS n, avg(len)::float AS avgdl
  FROM tmp_chunk_len WHERE book_id = $1::uuid
), qt AS (
  SELECT q.term, q.qtf, t.df::float AS df
  FROM q JOIN tmp_book_terms t ON t.term = q.term AND t.book_id = $1::uuid
), cands AS (
  SELECT c.id, c.tsv, l.len
  FROM chunks c JOIN tmp_chunk_len l ON l.id = c.id
  WHERE c.book_id = $1::uuid
    AND c.tsv @@ to_tsquery('simple', (
      SELECT string_agg(term, ' | ') FROM qt WHERE df <= $3 * (SELECT n FROM s)))
)
SELECT d.id
FROM cands d, unnest(d.tsv) u JOIN qt ON qt.term = u.lexeme, s
GROUP BY d.id, d.len, s.avgdl, s.n
ORDER BY sum(qt.qtf * ln(1 + (s.n - qt.df + 0.5) / (qt.df + 0.5))
             * cardinality(u.positions) * ($4 + 1)
             / (cardinality(u.positions) + $4 * (1 - $5 + $5 * d.len / s.avgdl))) DESC
LIMIT $6
"""


async def main() -> None:
    rows = [json.loads(x) for x in QUESTIONS.read_text(encoding="utf-8").splitlines() if x]
    rows = [r for r in rows if r["kind"] == "blind"]
    queries = [r["question"] for r in rows]
    conn = await asyncpg.connect(DATABASE_URL)
    html_book = str(await conn.fetchval("SELECT id FROM books WHERE title=$1", gap.HTML_TITLE))
    qvecs = cached("q_ollama", lambda: ollama_embed(queries))
    await conn.execute("DROP TABLE IF EXISTS tmp_chunk_len, tmp_book_terms")
    await conn.execute(
        "CREATE TABLE tmp_chunk_len AS SELECT id, book_id, "
        "(SELECT sum(cardinality(positions)) FROM unnest(tsv)) AS len FROM chunks"
    )
    await conn.execute(
        "CREATE TABLE tmp_book_terms AS SELECT c.book_id, u.lexeme AS term, count(*) AS df "
        "FROM chunks c, unnest(c.tsv) u GROUP BY 1, 2"
    )
    await conn.execute("CREATE INDEX ON tmp_book_terms (book_id, term)")
    await conn.execute("CREATE INDEX ON tmp_chunk_len (book_id)")
    report: dict[str, Any] = {}
    for name, book in (("P", gap.BOOK_ID), ("H", html_book)):
        recs = await conn.fetch(
            "SELECT id, text FROM chunks WHERE book_id=$1::uuid ORDER BY ordinal", book
        )
        index = {str(r["id"]): i for i, r in enumerate(recs)}
        normed = [norm(r["text"]) for r in recs]
        gold = [{i for i, t in enumerate(normed) if norm(r["evidence"]) in t} for r in rows]
        dense, _ = await app_legs(conn, book, queries, qvecs.tolist(), index)
        res: dict[str, Any] = {}
        for share in (1.0, 0.5, 0.2, 0.1, 0.05):
            leg, t = await sql_leg(
                conn,
                book,
                queries,
                index,
                SQL,
                lambda b, q, s, share=share: (b, q, share, K1, B, CANDIDATES),
            )
            fused = [rrf([a, b]) for a, b in zip(dense, leg, strict=True)]
            alone, together = score(leg, gold), score(fused, gold)
            for m in (alone, together):
                m.pop("_hits1"), m.pop("_hits5")
            res[f"rare<= {share}"] = {"leg": alone, "fused": together, "latency": lat(t)}
            print(
                f"{name} share {share:4}: leg Hit@5 {alone['hit@5']:5.1f}  fused Hit@1 "
                f"{together['hit@1']:5.1f} Hit@5 {together['hit@5']:5.1f}  {lat(t)}"
            )
        report[name] = res
    await conn.execute("DROP TABLE tmp_chunk_len, tmp_book_terms")
    await conn.close()
    (gap.HERE / "results" / "fts-bounded-208.json").write_text(
        json.dumps(report, indent=1), encoding="utf-8"
    )


if __name__ == "__main__":
    asyncio.run(main())
