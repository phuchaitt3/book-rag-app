"""`python -m book_rag_worker init|run`."""

import asyncio
import logging
import sys

from book_rag_api.observability import configure_logging
from book_rag_api.tracing import OtelTracer, build_tracing, instrument_engine
from book_rag_worker import ingest
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
    try:
        async with worker.app.open_async():
            await worker.app.run_worker_async()
    finally:
        if worker.index is not None:
            await worker.index.close()
        await worker.engine.dispose()


def main() -> None:
    configure_logging(level=logging.INFO)
    if sys.platform == "win32":  # psycopg's async mode needs a selector loop
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    command = sys.argv[1] if len(sys.argv) > 1 else "run"
    settings = get_worker_settings()
    provider = build_tracing(settings.otel_exporter_otlp_endpoint, service_name="book-rag-worker")
    if provider is not None:
        ingest.set_tracer(OtelTracer.from_provider(provider))
    worker = build_worker(settings)
    if provider is not None:
        instrument_engine(worker.engine, provider)
    if command == "init":
        asyncio.run(init_schema(worker))
    elif command == "run":
        try:
            asyncio.run(run(worker))
        finally:
            if provider is not None:
                provider.shutdown()  # flushes spans still queued for the collector
    else:
        sys.exit("usage: python -m book_rag_worker [init|run]")


if __name__ == "__main__":
    main()
