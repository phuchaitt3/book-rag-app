import math
from collections.abc import Iterator
from typing import Any

import pytest

from book_rag.providers import (
    LLM,
    Embedder,
    FakeEmbedder,
    FakeLLM,
    FakeReranker,
    Message,
    OllamaEmbedder,
    OllamaLLM,
    Reranker,
)


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_fakes_satisfy_the_protocols() -> None:
    assert isinstance(FakeLLM(), LLM)
    assert isinstance(FakeEmbedder(), Embedder)
    assert isinstance(FakeReranker(), Reranker)


async def test_fake_llm_streams_pieces_that_join_to_the_reply() -> None:
    pieces = [p async for p in FakeLLM("xin chào các bạn").stream([Message("user", "hi")])]
    assert len(pieces) == 4
    assert "".join(pieces) == "xin chào các bạn"


async def test_fake_llm_echoes_last_user_message() -> None:
    messages = [Message("system", "s"), Message("user", "một"), Message("user", "hai")]
    assert "".join([p async for p in FakeLLM().stream(messages)]) == "echo: hai"


async def test_fake_embedder_is_deterministic_with_fixed_dimension() -> None:
    embedder = FakeEmbedder(dimension=16)
    first = await embedder.embed(["Truyện Kiều", "chương một"])
    again = await embedder.embed(["Truyện Kiều", "chương một"])
    assert first == again
    assert embedder.dimension == 16
    assert all(len(v) == 16 for v in first)
    assert all(math.isclose(cosine(v, v), 1.0) for v in first)


async def test_fake_embedder_similar_texts_are_closer() -> None:
    a, b, c = await FakeEmbedder(64).embed(
        ["con mèo ngồi trên thảm", "con mèo ngồi trên ghế", "định lý Pythagoras"]
    )
    assert cosine(a, b) > cosine(a, c)


async def test_fake_embedder_handles_empty_text() -> None:
    [vec] = await FakeEmbedder(8).embed([""])
    assert math.isclose(cosine(vec, vec), 1.0)


def test_fake_embedder_rejects_bad_dimension() -> None:
    with pytest.raises(ValueError):
        FakeEmbedder(0)


async def test_fake_reranker_orders_by_word_overlap() -> None:
    scores = await FakeReranker().rerank("mèo ngồi", ["chó chạy", "mèo ngồi yên", "mèo chạy"])
    assert scores == [0.0, 1.0, 0.5]
    assert await FakeReranker().rerank("", ["a"]) == [0.0]


async def test_ollama_llm_streams_content_and_builds_payload() -> None:
    seen: list[tuple[str, dict[str, Any]]] = []

    def post(url: str, payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
        seen.append((url, payload))
        yield {"message": {"content": "Xin"}}
        yield {"message": {"content": " chào"}}
        yield {"message": {"content": ""}, "done": True}

    llm = OllamaLLM("qwen", base_url="http://h:1/", post=post)
    out = [p async for p in llm.stream([Message("user", "hi")])]
    assert out == ["Xin", " chào"]
    assert seen[0][0] == "http://h:1/api/chat"
    assert seen[0][1]["messages"] == [{"role": "user", "content": "hi"}]
    assert seen[0][1]["stream"] is True


async def test_ollama_embedder_checks_dimension() -> None:
    def post(url: str, payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
        yield {"embeddings": [[0.1, 0.2, 0.3] for _ in payload["input"]]}

    good = OllamaEmbedder("bge-m3", dimension=3, post=post)
    assert await good.embed(["a", "b"]) == [[0.1, 0.2, 0.3]] * 2
    assert await good.embed([]) == []
    with pytest.raises(ValueError):
        await OllamaEmbedder("bge-m3", dimension=1024, post=post).embed(["a"])
