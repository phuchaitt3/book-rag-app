"""Deterministic providers for unit tests and load tests (no model, no network, no cost)."""

from __future__ import annotations

import asyncio
import hashlib
import math
import random
import re
from collections.abc import AsyncIterator, Sequence

from book_rag.providers.base import Message

_WORD = re.compile(r"\w+", re.UNICODE)


def _words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text)]


class _Faults:
    """Optional failure for a fake call. With the defaults it does nothing.

    `errors` is a scripted sequence, one entry per call: an exception is raised, None lets the
    call succeed; once it runs out, `error_rate` (a seeded random draw) decides. All randomness
    comes from `random.Random(seed)`, so a run repeats.
    """

    def __init__(
        self,
        error_rate: float,
        errors: Sequence[Exception | None] | None,
        error: Exception | None,
        seed: int,
    ) -> None:
        if not 0.0 <= error_rate <= 1.0:
            raise ValueError("error_rate must be between 0 and 1")
        self._rate = error_rate
        self._script = list(errors or [])
        self._error = error
        self._rng = random.Random(seed)

    def next_error(self) -> Exception | None:
        if self._script:
            return self._script.pop(0)
        if self._rate > 0.0 and self._rng.random() < self._rate:
            return self._error or RuntimeError("injected fake provider error")
        return None


async def _sleep(seconds: float) -> None:
    if seconds > 0.0:
        await asyncio.sleep(seconds)


class FakeLLM:
    """Streams a fixed reply word by word; with no reply set, echoes the last user message.

    Optional load-test settings (all off by default): `first_token_delay` and `token_delay`
    (seconds, awaited with asyncio.sleep), and `error_rate` / `errors` / `error` / `seed` to
    raise a plain exception before the first token (see `_Faults`).
    """

    def __init__(
        self,
        reply: str | None = None,
        *,
        first_token_delay: float = 0.0,
        token_delay: float = 0.0,
        error_rate: float = 0.0,
        errors: Sequence[Exception | None] | None = None,
        error: Exception | None = None,
        seed: int = 0,
    ) -> None:
        self._reply = reply
        self._first_token_delay = first_token_delay
        self._token_delay = token_delay
        self._faults = _Faults(error_rate, errors, error, seed)

    async def stream(self, messages: Sequence[Message]) -> AsyncIterator[str]:
        failure = self._faults.next_error()
        await _sleep(self._first_token_delay)
        if failure is not None:
            raise failure
        text = self._reply
        if text is None:
            user = [m.content for m in messages if m.role == "user"]
            text = f"echo: {user[-1]}" if user else "echo:"
        for i, word in enumerate(text.split(" ")):
            if i > 0:
                await _sleep(self._token_delay)
            yield word if i == 0 else f" {word}"


class FakeEmbedder:
    """Hashes each word into a bucket, then L2-normalises: equal texts give equal vectors,
    texts that share words get a higher cosine similarity.

    Optional load-test settings (all off by default): `batch_delay` (seconds per `embed` call)
    and `error_rate` / `errors` / `error` / `seed` to raise a plain exception (see `_Faults`).
    """

    def __init__(
        self,
        dimension: int = 32,
        *,
        batch_delay: float = 0.0,
        error_rate: float = 0.0,
        errors: Sequence[Exception | None] | None = None,
        error: Exception | None = None,
        seed: int = 0,
    ) -> None:
        if dimension < 1:
            raise ValueError("dimension must be positive")
        self._dimension = dimension
        self._batch_delay = batch_delay
        self._faults = _Faults(error_rate, errors, error, seed)

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        failure = self._faults.next_error()
        await _sleep(self._batch_delay)
        if failure is not None:
            raise failure
        return [self._vector(t) for t in texts]

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self._dimension
        for word in _words(text):
            digest = hashlib.sha256(word.encode()).digest()
            vec[int.from_bytes(digest[:4], "big") % self._dimension] += 1.0
        norm = math.sqrt(sum(x * x for x in vec))
        if norm == 0.0:
            vec[0] = 1.0
            return vec
        return [x / norm for x in vec]


class FakeReranker:
    """Scores by the share of query words found in the document."""

    async def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        wanted = set(_words(query))
        if not wanted:
            return [0.0 for _ in documents]
        return [len(wanted & set(_words(d))) / len(wanted) for d in documents]
