"""`python -m book_rag_worker init|run`."""

import asyncio
import logging
import signal
import sys
from collections.abc import Callable
from typing import Any

from book_rag_api.observability import configure_logging
from book_rag_worker.config import get_worker_settings
from book_rag_worker.worker import Worker, build_worker

log = logging.getLogger(__name__)


async def init_schema(worker: Worker) -> None:
    """Create the queue tables unless they exist (Procrastinate's schema is not idempotent)."""
    async with worker.app.open_async():
        rows = await worker.app.connector.execute_query_all_async(
            "SELECT to_regclass('public.procrastinate_jobs') AS t"
        )
        if rows[0]["t"] is None:
            await worker.app.schema_manager.apply_schema_async()


def stop_on_signals(stop: asyncio.Event) -> Callable[[], None]:
    """Set `stop` on SIGTERM and SIGINT; returns a function that undoes it.

    Windows has no loop signal handlers, so there `signal.signal` is used (SIGTERM is not
    delivered there; Ctrl+C is). Tests set the event themselves and never send a signal.
    """
    loop = asyncio.get_running_loop()
    signals = [signal.SIGINT, signal.SIGTERM]
    installed: list[signal.Signals] = []
    previous: dict[signal.Signals, Any] = {}
    for sig in signals:
        try:
            loop.add_signal_handler(sig, stop.set)
            installed.append(sig)
        except (NotImplementedError, RuntimeError):
            previous[sig] = signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))

    def undo() -> None:
        for sig in installed:
            loop.remove_signal_handler(sig)
        for sig, handler in previous.items():
            signal.signal(sig, handler)

    return undo


async def run(worker: Worker, stop: asyncio.Event | None = None) -> None:
    """Work until `stop` is set (SIGTERM or SIGINT set it when `stop` is not given).

    Stopping takes no new job and gives the running one `worker.shutdown_timeout` seconds; if it
    is still running then, it is cancelled and returned to the queue (see `ingest`), so it is
    runnable again. Then the pools are closed and `run` returns, so the process exits 0.
    """
    own_stop = stop is None
    if stop is None:
        stop = asyncio.Event()
    undo = stop_on_signals(stop) if own_stop else None
    try:
        async with worker.app.open_async():
            queue = asyncio.create_task(
                worker.app.run_worker_async(
                    install_signal_handlers=False, shutdown_graceful_timeout=worker.shutdown_timeout
                )
            )
            stopper = asyncio.create_task(stop.wait())
            try:
                await asyncio.wait({queue, stopper}, return_when=asyncio.FIRST_COMPLETED)
                if not queue.done():
                    log.info("stop requested; finishing or releasing the current job")
                    queue.cancel()  # the queue's own graceful path: stop, wait, abort
                try:
                    await queue
                except asyncio.CancelledError:
                    if not stop.is_set():
                        raise
            finally:
                stopper.cancel()
    finally:
        if undo is not None:
            undo()
        if worker.index is not None:
            await worker.index.close()
        await worker.engine.dispose()


def main() -> None:
    configure_logging(level=logging.INFO)
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
