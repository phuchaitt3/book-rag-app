"""Chat model behind an OpenAI-compatible server (llama.cpp `llama-server`, vLLM, hosted APIs).

Calls `POST {base_url}/v1/chat/completions` with `stream: true` and reads the server-sent events
(standard library only, no new dependencies). It serves a quantized GGUF file through llama.cpp
the same way the Ollama adapter serves a model through Ollama (ADR 0003, #245).
"""

from __future__ import annotations

import asyncio
import json
import urllib.request
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from typing import Any

from book_rag.providers.base import Message

# Posts a JSON payload and yields the raw lines of the response body.
LinePostFn = Callable[[str, dict[str, Any], dict[str, str]], Iterator[bytes]]


def http_post_lines(url: str, payload: dict[str, Any], headers: dict[str, str]) -> Iterator[bytes]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        yield from response


def parse_sse_pieces(lines: Iterator[bytes]) -> Iterator[str]:
    """Yield the text of each `data:` event of a chat-completions stream until `[DONE]`."""
    for raw in lines:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line.startswith("data:"):
            continue
        data = line[len("data:") :].strip()
        if data == "[DONE]":
            return
        event = json.loads(data)
        for choice in event.get("choices", []):
            piece = (choice.get("delta") or {}).get("content")
            if piece:
                yield piece


class OpenAICompatLLM:
    def __init__(
        self,
        model: str,
        base_url: str = "http://127.0.0.1:8080",
        api_key: str = "",
        post: LinePostFn = http_post_lines,
    ) -> None:
        self._model = model
        self._url = f"{base_url.rstrip('/')}/v1/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._post = post

    async def stream(self, messages: Sequence[Message]) -> AsyncIterator[str]:
        payload = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
        }
        pieces = parse_sse_pieces(self._post(self._url, payload, self._headers))
        sentinel = object()
        while (piece := await asyncio.to_thread(next, pieces, sentinel)) is not sentinel:
            assert isinstance(piece, str)
            yield piece
