"""`python -m book_rag_worker init|run`."""

import asyncio
import logging
import sys

from book_rag_worker.config import get_worker_settings
from book_rag_worker.worker import Worker, build_worker


async def init_schema(worker: Worker) -> None:
    """Create the queue tables unless they exist (Procrastinate's schema is not idempotent)."""
    async with worker.app.open_async():
        rows = await worker.app.connector.execute_query_all_async(
            "SELECT to_regclass('public.procrastinate_jobs') AS t"
        )
        if rows[0]["t"] is None:
            await worker.app.schema_manager.apply_schema_async()


async def run(worker: Worker) -> None:
    async with worker.app.open_async():
        await worker.app.run_worker_async()
    await worker.engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if sys.platform == "win32":  # psycopg's async mode needs a selector loop
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    command = sys.argv[1] if len(sys.argv) > 1 else "run"
    worker = build_worker(get_worker_settings())
    if command == "init":
        asyncio.run(init_schema(worker))
    elif command == "run":
        asyncio.run(run(worker))
    else:
        sys.exit("usage: python -m book_rag_worker [init|run]")


if __name__ == "__main__":
    main()
