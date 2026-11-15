"""The shipped SQL leg with and without syllable bigrams (migration 0007), scored and timed (#95).

fts_accent.py chose arm C in memory. This runs the app's own `BM25_SEARCH` (bounded candidates,
stored statistics, ADR 0011) on a throwaway Postgres built by the app's migrations: first with
the statistics of `chunks.tsv` (unigrams: the leg as merged), then with those of `chunks.tsv_bi`
(unigrams and bigrams: the leg after 0007). It fuses each with the dense leg exactly as
fts_accent.py does, and reports per-query time and index and statistics sizes.

  BOOK_ID=x DUMP_DIR=<dir> uv run --with scipy python experiments/e2e/fts_accent_sql.py
Writes experiments/e2e/results/fts-accent-sql-95.json.
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

os.environ.setdefault("BOOK_ID", "unused")
import gap
import numpy as np
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.community.postgres import PostgresContainer

from book_rag_api.lexical import BM25_SEARCH, K1, RARE_SHARE, B

DUMP = Path(os.environ["DUMP_DIR"])
OUT = gap.HERE / "results" / "fts-accent-sql-95.json"
ALEMBIC_INI = gap.ROOT / "apps" / "api" / "alembic.ini"

# The merged leg: the same statement over `tsv`, and a plain `to_tsquery` for the candidates.
OLD_SEARCH = text(
    BM25_SEARCH.text.replace(
        "unnest(to_tsvector('simple', :query) || bigram_tsvector(:query))",
        "unnest(to_tsvector('simple', :query))",
    )
    .replace("c.tsv_bi", "c.tsv")
    .replace("d.tsv_bi", "d.tsv")
    .replace("CAST(coalesce(", "to_tsquery('simple', coalesce(")
    .replace("FROM qt)) AS tsquery)", "FROM qt)))")
)

STATS = {
    "tsv": [
        "UPDATE chunks SET token_count = "
        "(SELECT coalesce(sum(cardinality(positions)), 0) FROM unnest(tsv))",
        "DELETE FROM book_terms",
        "INSERT INTO book_terms SELECT c.book_id, u.lexeme, count(*) "
        "FROM chunks c, unnest(c.tsv) u GROUP BY 1, 2",
    ],
    "tsv_bi": [
        "UPDATE chunks SET token_count = "
        "(SELECT coalesce(sum(cardinality(positions)), 0) FROM unnest(tsv_bi))",
        "DELETE FROM book_terms",
        "INSERT INTO book_terms SELECT c.book_id, u.lexeme, count(*) "
        "FROM chunks c, unnest(c.tsv_bi) u GROUP BY 1, 2",
    ],
}


async def main() -> None:
    rows = [json.loads(x) for x in gap.QUESTIONS.read_text(encoding="utf-8").splitlines() if x]
    rows = [r for r in rows if r["kind"] == "blind"]
    queries = [r["question"] for r in rows]
    qv = np.load(Path(os.environ["CACHE_DIR"]) / "q_accent95.npy")
    qv = qv / np.linalg.norm(qv, axis=1, keepdims=True)
    report: dict[str, Any] = {"corpora": {}}
    pg = PostgresContainer("pgvector/pgvector:pg17", driver="asyncpg").with_name("book-rag-95-sql")
    pg.with_kwargs(mem_limit="1g", shm_size="128m")
    with pg:
        url = pg.get_connection_url()
        cfg = Config(str(ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", url)
        await asyncio.to_thread(command.upgrade, cfg, "head")
        engine = create_async_engine(url)
        async with engine.begin() as conn:
            for name, file in (("P", "pdf.jsonl"), ("H", "html.jsonl")):
                recs = [
                    json.loads(x) for x in (DUMP / file).read_text(encoding="utf-8").splitlines()
                ]
                texts = [r["text"] for r in recs]
                book = uuid4()
                await conn.execute(
                    text("INSERT INTO books (id, title, owner_id) VALUES (:i, :t, 'o')"),
                    {"i": book, "t": name},
                )
                await conn.execute(
                    text(
                        "INSERT INTO chunks (id, book_id, ordinal, text) "
                        "VALUES (gen_random_uuid(), :b, :o, :t)"
                    ),
                    [{"b": book, "o": i, "t": t} for i, t in enumerate(texts)],
                )
                cv = np.asarray([json.loads(r["emb"]) for r in recs], dtype=np.float32)
                cv /= np.linalg.norm(cv, axis=1, keepdims=True)
                gold = [
                    {i for i, t in enumerate(map(gap.norm, texts)) if gap.norm(r["evidence"]) in t}
                    for r in rows
                ]
                dense = gap.top_n(qv @ cv.T + 1.0, gap.CANDIDATES)
                arms: dict[str, list[list[int]]] = {"dense only": dense}
                timing: dict[str, Any] = {}
                for label, col, sql in (
                    ("tsv (merged leg)", "tsv", OLD_SEARCH),
                    ("tsv_bi (after 0007)", "tsv_bi", BM25_SEARCH),
                ):
                    for stmt in STATS[col]:
                        await conn.execute(text(stmt))
                    await conn.execute(text("ANALYZE chunks"))
                    leg, times = [], []
                    for q in queries + queries:  # the second pass is the timed one (warm)
                        t0 = time.perf_counter()
                        res = await conn.execute(
                            sql,
                            {
                                "book_id": book,
                                "owner_id": "o",
                                "query": q,
                                "share": RARE_SHARE,
                                "k1": K1,
                                "b": B,
                                "limit": gap.CANDIDATES,
                            },
                        )
                        ids = [r.id for r in res]
                        times.append((time.perf_counter() - t0) * 1000)
                        leg.append(ids)
                    leg, times = leg[len(queries) :], times[len(queries) :]
                    order = {
                        r.id: r.ordinal
                        for r in await conn.execute(
                            text("SELECT id, ordinal FROM chunks WHERE book_id = :b"), {"b": book}
                        )
                    }
                    leg_i = [[order[i] for i in ids] for ids in leg]
                    arms[f"{label} alone"] = leg_i
                    arms[f"{label} + dense"] = [
                        gap.rrf([d, x]) for d, x in zip(dense, leg_i, strict=True)
                    ]
                    timing[label] = {
                        "median_ms": round(statistics.median(times), 2),
                        "p95_ms": round(sorted(times)[int(0.95 * len(times))], 2),
                        "terms_rows": await conn.scalar(
                            text("SELECT count(*) FROM book_terms WHERE book_id = :b"), {"b": book}
                        ),
                    }
                scored = {a: gap.score(r, gold) for a, r in arms.items()}
                for m in scored.values():
                    m.pop("_hits1"), m.pop("_hits5")
                sizes = {
                    "ix_chunks_tsv_bytes": await conn.scalar(
                        text("SELECT pg_relation_size('ix_chunks_tsv')")
                    ),
                    "ix_chunks_tsv_bi_bytes": await conn.scalar(
                        text("SELECT pg_relation_size('ix_chunks_tsv_bi')")
                    ),
                    "tsv_column_bytes": await conn.scalar(
                        text("SELECT sum(pg_column_size(tsv)) FROM chunks WHERE book_id = :b"),
                        {"b": book},
                    ),
                    "tsv_bi_column_bytes": await conn.scalar(
                        text("SELECT sum(pg_column_size(tsv_bi)) FROM chunks WHERE book_id = :b"),
                        {"b": book},
                    ),
                }
                report["corpora"][name] = {
                    "chunks": len(texts),
                    "arms": scored,
                    "latency": timing,
                    "sizes": sizes,
                }
                print(f"\ncorpus {name}: {len(texts)} chunks {sizes}\n  latency {timing}")
                for a, m in scored.items():
                    print(
                        f"  {a:34s} Hit@1 {m['hit@1']:5.1f}  Hit@5 {m['hit@5']:5.1f} "
                        f"{m['hit@5_ci95']}"
                    )
        await engine.dispose()
    OUT.write_text(json.dumps(report, indent=1), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
