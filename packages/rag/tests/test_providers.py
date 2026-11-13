import asyncio
import math
import time
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
    TeiReranker,
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


async def test_tei_reranker_puts_scores_back_in_document_order() -> None:
    seen: list[tuple[str, dict[str, Any], float]] = []

    def post(url: str, payload: dict[str, Any], timeout: float) -> Any:
        seen.append((url, payload, timeout))
        # TEI answers best first, by index.
        return [{"index": 2, "score": 0.9}, {"index": 0, "score": 0.5}, {"index": 1, "score": 0.1}]

    reranker = TeiReranker("http://tei:80/", timeout=3.0, post=post)
    assert isinstance(reranker, Reranker)
    assert await reranker.rerank("sông Hồng", ["a", "b", "c"]) == [0.5, 0.1, 0.9]
    assert seen == [
        (
            "http://tei:80/rerank",
            {"query": "sông Hồng", "texts": ["a", "b", "c"], "truncate": True},
            3.0,
        )
    ]


async def test_tei_reranker_skips_the_call_for_no_documents() -> None:
    def post(url: str, payload: dict[str, Any], timeout: float) -> Any:
        raise AssertionError("should not be called")

    assert await TeiReranker(post=post).rerank("q", []) == []


async def test_tei_reranker_rejects_a_reply_missing_a_document() -> None:
    def post(url: str, payload: dict[str, Any], timeout: float) -> Any:
        return [{"index": 0, "score": 0.5}]

    with pytest.raises(ValueError):
        await TeiReranker(post=post).rerank("q", ["a", "b"])


async def _llm_outcomes(llm: FakeLLM, n: int) -> list[bool]:
    result = []
    for _ in range(n):
        try:
            _ = [p async for p in llm.stream([Message("user", "hi")])]
            result.append(True)
        except RuntimeError:
            result.append(False)
    return result


async def test_fake_llm_delays_first_token_and_each_token() -> None:
    llm = FakeLLM("a b c", first_token_delay=0.02, token_delay=0.01)
    start = time.perf_counter()
    pieces = [p async for p in llm.stream([Message("user", "hi")])]
    assert "".join(pieces) == "a b c"
    assert time.perf_counter() - start >= 0.035


async def test_fake_llm_scripted_errors_then_success() -> None:
    llm = FakeLLM("ok", errors=[TimeoutError("scripted"), None])
    with pytest.raises(TimeoutError):
        _ = [p async for p in llm.stream([Message("user", "hi")])]
    for _ in range(2):
        assert "".join([p async for p in llm.stream([Message("user", "hi")])]) == "ok"


async def test_fake_llm_error_rate_repeats_with_the_same_seed() -> None:
    first = await _llm_outcomes(FakeLLM("ok", error_rate=0.5, seed=7), 30)
    second = await _llm_outcomes(FakeLLM("ok", error_rate=0.5, seed=7), 30)
    assert first == second
    assert True in first
    assert False in first
    assert all(await _llm_outcomes(FakeLLM("ok", error_rate=0.0), 5))
    assert not any(await _llm_outcomes(FakeLLM("ok", error_rate=1.0), 5))


async def test_fake_llm_delays_overlap_across_concurrent_streams() -> None:
    async def run() -> None:
        _ = [p async for p in FakeLLM("a b", first_token_delay=0.03).stream([])]

    start = time.perf_counter()
    await asyncio.gather(*(run() for _ in range(10)))
    assert time.perf_counter() - start < 0.25


async def test_fake_embedder_delay_and_scripted_error() -> None:
    embedder = FakeEmbedder(8, batch_delay=0.02, errors=[ConnectionError("429")])
    with pytest.raises(ConnectionError):
        await embedder.embed(["x"])
    start = time.perf_counter()
    vectors = await embedder.embed(["x", "y"])
    assert len(vectors) == 2
    assert time.perf_counter() - start >= 0.015


async def test_fake_embedder_error_rate_is_seeded() -> None:
    async def run(seed: int) -> list[bool]:
        embedder = FakeEmbedder(8, error_rate=0.5, seed=seed)
        out = []
        for _ in range(30):
            try:
                await embedder.embed(["x"])
                out.append(True)
            except RuntimeError:
                out.append(False)
        return out

    assert await run(3) == await run(3)


def test_fake_error_rate_must_be_a_probability() -> None:
    with pytest.raises(ValueError):
        FakeLLM(error_rate=1.5)
    with pytest.raises(ValueError):
        FakeEmbedder(error_rate=-0.1)
