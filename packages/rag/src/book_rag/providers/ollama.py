"""Local providers backed by an Ollama server (standard library only, no new dependencies).

A self-hosted reranker (bge-reranker-v2-m3) needs a model runtime, so it waits for the
dependency change that adds one; hosted providers come after the eval (M3).
"""

from __future__ import annotations

import asyncio
import json
import urllib.request
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from typing import Any

from book_rag.providers.base import Message

# Posts a JSON payload and yields the decoded JSON lines of the response.
PostFn = Callable[[str, dict[str, Any]], Iterator[dict[str, Any]]]


def http_post(url: str, payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        for line in response:
            if line.strip():
                yield json.loads(line)


class OllamaLLM:
    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
        post: PostFn = http_post,
    ) -> None:
        self._model = model
        self._url = f"{base_url.rstrip('/')}/api/chat"
        self._post = post

    async def stream(self, messages: Sequence[Message]) -> AsyncIterator[str]:
        payload = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
        }
        lines = self._post(self._url, payload)
        sentinel = object()
        while (line := await asyncio.to_thread(next, lines, sentinel)) is not sentinel:
            assert isinstance(line, dict)
            piece = line.get("message", {}).get("content", "")
            if piece:
                yield piece


class OllamaEmbedder:
    def __init__(
        self,
        model: str,
        dimension: int,
        base_url: str = "http://localhost:11434",
        post: PostFn = http_post,
    ) -> None:
        self._model = model
        self._dimension = dimension
        self._url = f"{base_url.rstrip('/')}/api/embed"
        self._post = post

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = {"model": self._model, "input": list(texts)}
        reply = await asyncio.to_thread(lambda: next(self._post(self._url, payload)))
        vectors: list[list[float]] = reply["embeddings"]
        if len(vectors) != len(texts) or any(len(v) != self._dimension for v in vectors):
            raise ValueError(
                f"embedder returned vectors that are not of dimension {self._dimension}"
            )
        return vectors
