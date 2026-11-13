import procrastinate
import pytest
from procrastinate import testing
from sqlalchemy.ext.asyncio import create_async_engine

from book_rag_worker.__main__ import run
from book_rag_worker.worker import Worker


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
