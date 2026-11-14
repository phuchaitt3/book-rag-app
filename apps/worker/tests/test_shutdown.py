import asyncio

import procrastinate
import pytest
from procrastinate import testing
from sqlalchemy.ext.asyncio import create_async_engine

from book_rag_worker.__main__ import run
from book_rag_worker.worker import RetryStrategy, Worker


class FakeIndex:
    def __init__(self) -> None:
        self.closed = 0

    async def close(self) -> None:
        self.closed += 1


async def test_run_closes_the_qdrant_index_at_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    app = procrastinate.App(connector=testing.InMemoryConnector())

    async def run_worker_async(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(app, "run_worker_async", run_worker_async)
    index = FakeIndex()
    engine = create_async_engine("postgresql+asyncpg://x:x@127.0.0.1:1/x")
    await run(Worker(app, engine, index))  # type: ignore[arg-type]
    assert index.closed == 1


async def test_run_returns_when_the_stop_event_is_set() -> None:
    """No signal is sent: the event is what a SIGTERM handler sets."""
    app = procrastinate.App(connector=testing.InMemoryConnector())
    engine = create_async_engine("postgresql+asyncpg://x:x@127.0.0.1:1/x")
    stop = asyncio.Event()
    task = asyncio.create_task(run(Worker(app, engine, None, 1.0), stop))
    await asyncio.sleep(0.2)
    assert not task.done()  # still working: waiting for jobs
    stop.set()
    await asyncio.wait_for(task, 10)  # returns normally, so the process exits 0


def test_a_job_cut_off_by_shutdown_is_retried_at_once() -> None:
    retry = RetryStrategy(max_attempts=2, exponential_wait=3, retry_exceptions=[ValueError])
    job = procrastinate.jobs.Job(
        id=1, queue="default", lock=None, queueing_lock=None, task_name="t", task_kwargs={}
    )
    for exc in (asyncio.CancelledError(), procrastinate.exceptions.JobAborted()):
        decision = retry.get_retry_decision(exception=exc, job=job)
        assert decision is not None
        assert decision.retry_at is None  # no backoff
    assert retry.get_retry_decision(exception=RuntimeError("bad pdf"), job=job) is None
