"""A per-key sliding-window rate limiter, kept in this process's memory.

With several API instances each one counts on its own, so the real limit is the setting times
the number of instances. A shared limit (Redis, or the gateway in front of the API) needs a new
service; this one needs none and stops a single client from flooding one instance.
"""

import time
from collections import deque
from collections.abc import Callable


class RateLimiter:
    def __init__(
        self, limit: int, window: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.limit = limit
        self.window = window
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def check(self, key: str) -> float | None:
        """Record a request. Return None if allowed, else the seconds until one would be."""
        if self.limit <= 0:
            return None
        now = self._clock()
        if len(self._hits) > 10_000:
            self._forget_idle(now)
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return self.window - (now - hits[0])
        hits.append(now)
        return None

    def _forget_idle(self, now: float) -> None:
        for key in [k for k, h in self._hits.items() if not h or now - h[-1] >= self.window]:
            del self._hits[key]
