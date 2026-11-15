"""The API app with fake providers that have latency, plus a /load-stats route (#227).

Not part of the product: it only builds `create_app` with different providers and samples the
event loop and the database pool, which the product does not expose.
"""

import asyncio
import os
import time
from contextlib import asynccontextmanager

from book_rag.providers import FakeEmbedder, FakeLLM
from book_rag_api.main import create_app
from book_rag_api.models import EMBEDDING_DIM

REPLY = " ".join(f"từ{i}" for i in range(60))  # 60 words: the nominal stream is 0.8 + 59 * 0.03 s

app = create_app(
    llm=FakeLLM(
        REPLY,
        first_token_delay=float(os.environ["FAKE_FIRST_TOKEN_DELAY"]),
        token_delay=float(os.environ["FAKE_TOKEN_DELAY"]),
    ),
    embedder=FakeEmbedder(
        EMBEDDING_DIM, batch_delay=float(os.environ["FAKE_QUESTION_EMBED_DELAY"])
    ),
)

stats: dict[str, list[float]] = {"lag": [], "pool_wait": [], "checked_out": []}
_original = app.router.lifespan_context


async def _sample_loop(engine) -> None:  # type: ignore[no-untyped-def]
    while True:
        t = time.perf_counter()
        await asyncio.sleep(0.1)
        stats["lag"].append(time.perf_counter() - t - 0.1)
        stats["checked_out"].append(engine.sync_engine.pool.checkedout())


@asynccontextmanager
async def _lifespan(a):  # type: ignore[no-untyped-def]
    async with _original(a):
        pool = a.state.engine.sync_engine.pool
        connect = pool.connect

        def timed():  # type: ignore[no-untyped-def]
            t = time.perf_counter()
            try:
                return connect()
            finally:
                stats["pool_wait"].append(time.perf_counter() - t)

        pool.connect = timed
        task = asyncio.create_task(_sample_loop(a.state.engine))
        try:
            yield
        finally:
            task.cancel()


app.router.lifespan_context = _lifespan


def _pct(xs: list[float], q: float) -> float:
    return sorted(xs)[min(len(xs) - 1, int(q * len(xs)))] if xs else 0.0


@app.get("/load-stats", include_in_schema=False)
async def load_stats(reset: bool = False) -> dict[str, float]:
    out = {
        "lag_p95_ms": _pct(stats["lag"], 0.95) * 1000,
        "lag_max_ms": max(stats["lag"], default=0.0) * 1000,
        "pool_wait_p50_ms": _pct(stats["pool_wait"], 0.5) * 1000,
        "pool_wait_p95_ms": _pct(stats["pool_wait"], 0.95) * 1000,
        "pool_wait_max_ms": max(stats["pool_wait"], default=0.0) * 1000,
        "pool_checkouts": float(len(stats["pool_wait"])),
        "pool_checked_out_max": max(stats["checked_out"], default=0.0),
    }
    if reset:
        for v in stats.values():
            v.clear()
    return out
