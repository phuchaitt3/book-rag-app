import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def create_engine(database_url: str) -> AsyncEngine:
    # pool_pre_ping drops connections a scale-to-zero database closed while idle.
    return create_async_engine(database_url, pool_pre_ping=True)


async def ping(engine: AsyncEngine, timeout_s: float = 3.0) -> None:
    """Raise if the database does not answer within `timeout_s`."""
    async with asyncio.timeout(timeout_s), engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
