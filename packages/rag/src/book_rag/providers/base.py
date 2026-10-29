"""Interfaces for the external models. Everything model-shaped sits behind one of these."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class Message:
    role: Literal["system", "user", "assistant"]
    content: str


@runtime_checkable
class LLM(Protocol):
    """Chat model that streams its answer as text pieces."""

    def stream(self, messages: Sequence[Message]) -> AsyncIterator[str]: ...


@runtime_checkable
class Embedder(Protocol):
    """Turns texts into vectors of a fixed length (`dimension`)."""

    @property
    def dimension(self) -> int: ...

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


@runtime_checkable
class Reranker(Protocol):
    """Scores each document against the query; higher means more relevant."""

    async def rerank(self, query: str, documents: Sequence[str]) -> list[float]: ...
