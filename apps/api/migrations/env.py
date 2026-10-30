import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from book_rag_api.config import get_settings
from book_rag_api.models import Base

target_metadata = Base.metadata


def get_url() -> str:
    # A URL set on the Alembic config (tests do this) wins. Otherwise use the direct
    # (unpooled) connection: DDL and `CREATE EXTENSION` do not belong behind a pooler.
    configured = context.config.get_main_option("sqlalchemy.url")
    if configured:
        return configured
    settings = get_settings()
    return settings.database_url_unpooled or settings.database_url


def run_migrations_offline() -> None:
    context.configure(url=get_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(get_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
