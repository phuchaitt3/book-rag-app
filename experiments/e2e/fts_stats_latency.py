"""Latency of BM25 in Postgres when the book statistics are stored, not computed per query (#204).

fts_options.py computes document frequency and chunk length per query (an O(book) scan). This
stores them once (`chunk_len` and `book_terms` tables, created and dropped here) and times the
same query, to show what a stored-statistics design buys. Needs the Compose database.

  BOOK_ID=<uuid> uv run --with scipy python experiments/e2e/fts_stats_latency.py
"""

from __future__ import annotations

import asyncio
import json
import statistics
import time

import asyncpg  # type: ignore[import-untyped]
import gap
from gap import CANDIDATES, DATABASE_URL, QUESTIONS, or_query

SQL = """
WITH q AS (
  SELECT lexeme AS term, cardinality(positions) AS qtf FROM unnest(to_tsvector('simple', $2))
), s AS (
  SELECT count(*)::float AS n, avg(len)::float AS avgdl
  FROM tmp_chunk_len WHERE book_id=$1::uuid
)
SELECT c.id
FROM chunks c JOIN tmp_chunk_len l ON l.id = c.id, unnest(c.tsv) u
JOIN q ON q.term = u.lexeme
JOIN tmp_book_terms t ON t.term = u.lexeme AND t.book_id = $1::uuid, s
WHERE c.book_id = $1::uuid AND c.tsv @@ to_tsquery('simple', $3)
GROUP BY c.id, l.len, s.avgdl, s.n
ORDER BY sum(q.qtf * ln(1 + (s.n - t.df + 0.5) / (t.df + 0.5)) * cardinality(u.positions) * 2.2
             / (cardinality(u.positions) + 1.2 * (0.25 + 0.75 * l.len / s.avgdl))) DESC
LIMIT $4
"""


async def main() -> None:
    queries = [
        json.loads(x)["question"]
        for x in QUESTIONS.read_text(encoding="utf-8").splitlines()
        if x and json.loads(x)["kind"] == "blind"
    ]
    conn = await asyncpg.connect(DATABASE_URL)
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
    times = []
    for q in queries:
        t0 = time.perf_counter()
        await conn.fetch(SQL, gap.BOOK_ID, q, or_query(q), CANDIDATES)
        times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    rows = await conn.fetchval(
        "SELECT count(*) FROM tmp_book_terms WHERE book_id=$1::uuid", gap.BOOK_ID
    )
    print(
        {
            "median_ms": round(statistics.median(times), 2),
            "p95_ms": round(times[int(0.95 * len(times))], 2),
            "term_rows_for_book": rows,
        }
    )
    await conn.execute("DROP TABLE tmp_chunk_len, tmp_book_terms")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
