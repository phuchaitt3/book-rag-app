"""Deterministic providers for unit tests and load tests (no model, no network, no cost)."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import AsyncIterator, Sequence

from book_rag.providers.base import Message

_WORD = re.compile(r"\w+", re.UNICODE)


def _words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text)]


class FakeLLM:
    """Streams a fixed reply word by word; with no reply set, echoes the last user message."""

    def __init__(self, reply: str | None = None) -> None:
        self._reply = reply

    async def stream(self, messages: Sequence[Message]) -> AsyncIterator[str]:
        text = self._reply
        if text is None:
            user = [m.content for m in messages if m.role == "user"]
            text = f"echo: {user[-1]}" if user else "echo:"
        for i, word in enumerate(text.split(" ")):
            yield word if i == 0 else f" {word}"


class FakeEmbedder:
    """Hashes each word into a bucket, then L2-normalises: equal texts give equal vectors,
    texts that share words get a higher cosine similarity."""

    def __init__(self, dimension: int = 32) -> None:
        if dimension < 1:
            raise ValueError("dimension must be positive")
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
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
