"""Reranker served by Hugging Face Text Embeddings Inference (TEI), standard library only.

TEI runs the cross-encoder (bge-reranker-v2-m3 in Compose, ADR 0009) in its own container, so
the API image carries no model runtime. Its `/rerank` route takes the query and the texts and
returns `[{"index": i, "score": s}, ...]`, best first.
"""

from __future__ import annotations

import asyncio
import json
import urllib.request
from collections.abc import Callable, Sequence
from typing import Any

# Posts a JSON payload with a timeout in seconds and returns the decoded JSON reply.
JsonPostFn = Callable[[str, dict[str, Any], float], Any]


def post_json(url: str, payload: dict[str, Any], timeout: float) -> Any:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


class TeiReranker:
    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        timeout: float = 10.0,
        post: JsonPostFn = post_json,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/rerank"
        self._timeout = timeout
        self._post = post

    async def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        if not documents:
            return []
        # `truncate`: a chunk longer than the model's window is cut instead of refused.
        payload = {"query": query, "texts": list(documents), "truncate": True}
        reply = await asyncio.to_thread(self._post, self._url, payload, self._timeout)
        scores: list[float | None] = [None] * len(documents)
        for item in reply:
            scores[item["index"]] = float(item["score"])
        if any(s is None for s in scores):
            raise ValueError("reranker did not score every document")
        return [s for s in scores if s is not None]
