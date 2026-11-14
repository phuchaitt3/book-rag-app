"""Counts the answers being streamed, so shutdown can wait for them (#228)."""

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager, suppress


class StreamTracker:
    """In-flight streams, and a way to wait for them to end with a deadline."""

    def __init__(self) -> None:
        self.active = 0
        self.draining = False
        self._idle = asyncio.Event()
        self._idle.set()

    @contextmanager
    def track(self) -> Iterator[None]:
        self.active += 1
        self._idle.clear()
        try:
            yield
        finally:
            self.active -= 1
            if self.active == 0:
                self._idle.set()

    async def wrap(self, pieces: AsyncIterator[str]) -> AsyncIterator[str]:
        """Pass `pieces` through, counted as active until it ends or is cancelled."""
        with self.track():
            async for piece in pieces:
                yield piece

    async def drain(self, seconds: float) -> int:
        """Mark the process as draining (readiness turns 503) and wait up to `seconds`
        for the active streams to end. Returns how many are still running."""
        self.draining = True
        with suppress(TimeoutError):
            async with asyncio.timeout(seconds):
                await self._idle.wait()
        return self.active
