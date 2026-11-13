"""Growth of the full-text leg with the book's size (#208, the growth-rate item).

Times `SqlChunkSearcher.text_search` (BM25 from stored statistics, ADR 0011) and the
`ts_rank_cd` search it replaced, on synthetic books of growing chunk count, in a pgvector
container with a memory limit. SYNTHETIC: each chunk is a random draw of words from the real
book's word frequencies, with a real chunk's length, so a common word is as common as in real
text and an OR query matches nearly every chunk, as the 80 ms case of #204 did. Word order and
co-occurrence are lost, so this measures latency only, never quality. Queries are the 416
real test-set questions, 100 sampled per size.

Run from the repository root (needs Docker; no GPU):
  BOOK_DATA=<main checkout>/experiments/book-testset/data \\
  python ~/claude-config/scripts/gpu_run.py run --resource ram --wait -- \\
    uv run python experiments/e2e/fts_scale.py
Writes experiments/e2e/results/fts-scale-208.json.
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import random
import statistics
import time
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from book_rag_api.lexical import refresh_book_stats
from book_rag_api.models import Book, Chunk
from book_rag_api.retrieval import SqlChunkSearcher

ROOT = Path(__file__).parents[2]
DATA = Path(os.environ.get("BOOK_DATA", ROOT / "experiments" / "book-testset" / "data"))
QUESTIONS = ROOT / "experiments" / "book-testset" / "questions.jsonl"
OUT = Path(__file__).parent / "results" / "fts-scale-208.json"
SIZES = [int(x) for x in os.environ.get("SIZES", "392,3920,11760,39200").split(",")]
N_QUERIES = 100
LIMIT = 30
SEED = 208
MEM_LIMIT = "2g"


def pct(values: list[float], p: float) -> float:
    return sorted(values)[min(int(len(values) * p), len(values) - 1)]


async def main() -> None:
    real = [json.loads(x) for x in (DATA / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
    words = [w for c in real for w in c["text"].lower().split()]
    lengths = [len(c["text"].split()) for c in real]
    questions = [
        json.loads(x)["question"]
        for x in QUESTIONS.read_text(encoding="utf-8").splitlines()
        if json.loads(x)["kind"] != "unanswerable"
    ]
    rng = random.Random(SEED)
    queries = rng.sample(questions, N_QUERIES)

    container = PostgresContainer("pgvector/pgvector:pg17", driver="asyncpg")
    container.with_kwargs(mem_limit=MEM_LIMIT, shm_size="256m")
    results: list[dict[str, object]] = []
    with container as pg:
        url = pg.get_connection_url()
        config = Config(str(ROOT / "apps" / "api" / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", url)
        await asyncio.to_thread(command.upgrade, config, "head")
        engine = create_async_engine(url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        searcher = SqlChunkSearcher(sessions)

        for size in SIZES:
            book_id = uuid4()
            t0 = time.perf_counter()
            async with sessions.begin() as session:
                session.add(Book(id=book_id, title=f"synthetic-{size}"))
                await session.flush()
                for start in range(0, size, 2000):
                    session.add_all(
                        Chunk(
                            book_id=book_id,
                            ordinal=i,
                            text=" ".join(rng.choices(words, k=rng.choice(lengths))),
                            page=i // 3 + 1,
                        )
                        for i in range(start, min(start + 2000, size))
                    )
                    await session.flush()
                await refresh_book_stats(session, book_id)
            async with sessions() as session:
                await session.execute(text("ANALYZE chunks"))
                await session.execute(text("ANALYZE book_terms"))
                await session.commit()
            load_s = time.perf_counter() - t0

            arm_times: dict[str, list[float]] = {}
            for name, fn in (
                ("bm25_bounded", searcher.text_search),
                ("ts_rank_cd", searcher._ts_rank_search),
            ):
                for q in queries[:10]:  # warm-up, discarded
                    await fn(book_id, q, LIMIT)
                times = []
                for _ in range(2):
                    for q in queries:
                        t = time.perf_counter()
                        await fn(book_id, q, LIMIT)
                        times.append((time.perf_counter() - t) * 1000)
                arm_times[name] = times
            row = {
                "chunks": size,
                "load_s": round(load_s, 1),
                **{
                    f"{n}_{k}": round(v, 1)
                    for n, t in arm_times.items()
                    for k, v in (
                        ("median_ms", statistics.median(t)),
                        ("p95_ms", pct(t, 0.95)),
                    )
                },
            }
            results.append(row)
            print(json.dumps(row), flush=True)
            async with sessions.begin() as session:  # one book at a time in the table
                await session.execute(text("DELETE FROM chunks"))
                await session.execute(text("DELETE FROM book_terms"))
                await session.execute(text("DELETE FROM books"))
        await engine.dispose()

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "issue": 208,
                "synthetic": "random draws from the real book's word frequencies; latency only",
                "container_mem_limit": MEM_LIMIT,
                "queries": N_QUERIES,
                "limit": LIMIT,
                "seed": SEED,
                "python": platform.python_version(),
                "rows": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


asyncio.run(main())
