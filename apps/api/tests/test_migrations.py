import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.community.postgres import PostgresContainer

from book_rag_api.models import EMBEDDING_DIM

ALEMBIC_INI = Path(__file__).parents[1] / "alembic.ini"


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    # A fresh database with the pgvector image but no extension yet: the migration must create it.
    with PostgresContainer("pgvector/pgvector:pg17", driver="asyncpg") as pg:
        yield pg.get_connection_url()


def alembic_config(url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", url)
    return config


async def test_upgrade_creates_extension_and_tables(database_url: str) -> None:
    # env.py calls asyncio.run, so run Alembic off this event loop.
    await asyncio.to_thread(command.upgrade, alembic_config(database_url), "head")

    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            extensions = (await conn.execute(text("SELECT extname FROM pg_extension"))).scalars()
            assert "vector" in set(extensions)

            tables = (
                await conn.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                )
            ).scalars()
            assert {"books", "sections", "chunks", "ingestion_jobs"} <= set(tables)

            indexes = (
                await conn.execute(
                    text("SELECT indexname FROM pg_indexes WHERE tablename='chunks'")
                )
            ).scalars()
            assert {"ix_chunks_embedding_hnsw", "ix_chunks_tsv"} <= set(indexes)

            # Insert a chunk and find it through both retrieval paths.
            vector = "[" + ",".join(["0.1"] * EMBEDDING_DIM) + "]"
            await conn.execute(
                text(
                    "WITH b AS (INSERT INTO books (id, title) VALUES (gen_random_uuid(), 'T')"
                    " RETURNING id) INSERT INTO chunks (id, book_id, ordinal, text, embedding)"
                    " SELECT gen_random_uuid(), id, 0, 'Chào thế giới', CAST(:v AS vector) FROM b"
                ),
                {"v": vector},
            )
            nearest = await conn.execute(
                text("SELECT text FROM chunks ORDER BY embedding <=> CAST(:v AS vector) LIMIT 1"),
                {"v": vector},
            )
            assert nearest.scalar_one() == "Chào thế giới"
            full_text = await conn.execute(
                text("SELECT text FROM chunks WHERE tsv @@ plainto_tsquery('simple', 'thế giới')")
            )
            assert full_text.scalar_one() == "Chào thế giới"
    finally:
        await engine.dispose()


async def test_downgrade_drops_tables(database_url: str) -> None:
    config = alembic_config(database_url)
    await asyncio.to_thread(command.upgrade, config, "head")
    await asyncio.to_thread(command.downgrade, config, "base")

    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            tables = (
                await conn.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                )
            ).scalars()
            assert {"books", "chunks"}.isdisjoint(set(tables))
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    ("table", "constraint"),
    [("chunks", "uq_chunks_book_id_ordinal"), ("sections", "uq_sections_book_id_ordinal")],
)
async def test_ordinals_are_unique_per_book(database_url: str, table: str, constraint: str) -> None:
    await asyncio.to_thread(command.upgrade, alembic_config(database_url), "head")

    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            book_id = (
                await conn.execute(
                    text(
                        "INSERT INTO books (id, title) VALUES (gen_random_uuid(), 'U') RETURNING id"
                    )
                )
            ).scalar_one()
            if table == "chunks":
                columns, values = "text", "'x'"
            else:
                columns, values = "title, path, level", "'t', 't', 1"
        insert = text(
            f"INSERT INTO {table} (id, book_id, ordinal, {columns}) "
            f"VALUES (gen_random_uuid(), :b, 7, {values})"
        )
        async with engine.begin() as conn:
            await conn.execute(insert, {"b": book_id})
        with pytest.raises(IntegrityError, match=constraint):
            async with engine.begin() as conn:
                await conn.execute(insert, {"b": book_id})
    finally:
        await engine.dispose()
