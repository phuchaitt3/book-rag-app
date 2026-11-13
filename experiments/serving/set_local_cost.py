"""Cost of the extra `SET LOCAL` round trip in `SqlChunkSearcher.vector_search` (#93, item 3).

Starts a pgvector container, seeds one small book and 400 chunks of another (so the HNSW walk
needs iterative scan), then times three ways to run the same vector query:

  a. setup statement + query, as the app does today (two statements in one transaction)
  b. query only, no setting (one statement; returns too few rows, the bug the setting fixes)
  c. one statement, setting folded in with a CTE around `set_config(..., true)`

and checks how many of the book's chunks each returns. Run (RAM-heavy container, no GPU):

    python ~/claude-config/scripts/gpu_run.py run --resource ram --wait -- \\
        uv run python experiments/serving/set_local_cost.py
"""

import asyncio
import statistics
import time
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from book_rag.providers import FakeEmbedder
from book_rag_api.models import EMBEDDING_DIM, Book, Chunk

ALEMBIC_INI = Path(__file__).parents[2] / "apps" / "api" / "alembic.ini"
REPS = 300
LIMIT = 5


async def main() -> None:
    with PostgresContainer("pgvector/pgvector:pg17", driver="asyncpg") as pg:
        url = pg.get_connection_url()
        config = Config(str(ALEMBIC_INI))
        config.set_main_option("sqlalchemy.url", url)
        await asyncio.to_thread(command.upgrade, config, "head")

        embedder = FakeEmbedder(EMBEDDING_DIM)
        own = [f"own passage {i} about rivers" for i in range(LIMIT)]
        other = [f"other passage {i} about mountains" for i in range(400)]
        own_v, other_v = await embedder.embed(own), await embedder.embed(other)
        own_book, other_book = Book(id=uuid4(), title="own"), Book(id=uuid4(), title="other")
        engine = create_async_engine(url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions.begin() as session:
            session.add_all([own_book, other_book])
            await session.flush()
            session.add_all(
                Chunk(book_id=b.id, ordinal=i, text=t, embedding=v)
                for b, texts, vecs in ((own_book, own, own_v), (other_book, other, other_v))
                for i, (t, v) in enumerate(zip(texts, vecs, strict=True))
            )

        [q] = await embedder.embed([own[0]])
        stmt = (
            select(Chunk.id)
            .where(Chunk.book_id == own_book.id, Chunk.embedding.is_not(None))
            .order_by(Chunk.embedding.cosine_distance(q))
            .limit(LIMIT)
        )
        folded = text(
            "WITH s AS (SELECT set_config('hnsw.iterative_scan', 'strict_order', true)) "
            "SELECT c.id FROM chunks c, s WHERE c.book_id = :b AND c.embedding IS NOT NULL "
            "ORDER BY c.embedding <=> CAST(:q AS vector) LIMIT :n"
        )
        qtxt = "[" + ",".join(map(str, q)) + "]"

        async def a() -> int:
            async with sessions() as session:
                await session.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
                return len((await session.scalars(stmt)).all())

        async def b() -> int:
            async with sessions() as session:
                return len((await session.scalars(stmt)).all())

        async def c() -> int:
            async with sessions() as session:
                rows = await session.execute(folded, {"b": own_book.id, "q": qtxt, "n": LIMIT})
                return len(rows.all())

        print(f"{'arm':<28}{'rows':>5}{'median ms':>11}{'p95 ms':>9}")
        for name, fn in (
            ("a two statements", a),
            ("b query only (no setting)", b),
            ("c folded set_config CTE", c),
        ):
            await fn()  # warm up
            times, rows = [], 0
            for _ in range(REPS):
                t0 = time.perf_counter()
                rows = await fn()
                times.append((time.perf_counter() - t0) * 1000)
            times.sort()
            median, p95 = statistics.median(times), times[int(REPS * 0.95)]
            print(f"{name:<28}{rows:>5}{median:>11.2f}{p95:>9.2f}")
        await engine.dispose()


asyncio.run(main())
