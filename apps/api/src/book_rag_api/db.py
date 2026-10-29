import asyncio
from uuid import uuid4

from sqlalchemy import URL, make_url, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

# libpq options that asyncpg does not accept as query parameters.
_LIBPQ_ONLY = ("channel_binding",)


def to_asyncpg_url(database_url: str) -> URL:
    """Accept a plain libpq URL (as Neon and most hosts hand out) and return an asyncpg URL."""
    url = make_url(database_url)
    if url.drivername in ("postgres", "postgresql"):
        url = url.set(drivername="postgresql+asyncpg")
    query = {k: v for k, v in url.query.items() if k not in _LIBPQ_ONLY}
    if "sslmode" in query:
        query["ssl"] = query.pop("sslmode")
    return url.set(query=query)


def create_engine(database_url: str) -> AsyncEngine:
    # pool_pre_ping drops connections a scale-to-zero database closed while idle.
    # Unique prepared-statement names and no statement cache keep asyncpg safe behind
    # a transaction-mode pooler (PgBouncer, Neon's pooled URL).
    return create_async_engine(
        to_asyncpg_url(database_url),
        pool_pre_ping=True,
        connect_args={
            "statement_cache_size": 0,
            "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
        },
    )


async def ping(engine: AsyncEngine, timeout_s: float = 3.0) -> None:
    """Raise if the database does not answer within `timeout_s`."""
    async with asyncio.timeout(timeout_s), engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
