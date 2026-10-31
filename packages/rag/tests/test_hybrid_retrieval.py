from collections.abc import Sequence
from uuid import UUID, uuid4

import pytest

from book_rag.providers import FakeEmbedder, FakeReranker
from book_rag.retrieval import HybridRetriever, RetrievedChunk, reciprocal_rank_fusion


def chunk(text: str) -> RetrievedChunk:
    return RetrievedChunk(id=uuid4(), text=text, page=1, section_path=None)


class StubSearcher:
    def __init__(self, by_vector: list[RetrievedChunk], by_text: list[RetrievedChunk]) -> None:
        self.by_vector, self.by_text = by_vector, by_text

    async def vector_search(
        self, book_id: UUID, embedding: Sequence[float], limit: int
    ) -> list[RetrievedChunk]:
        return self.by_vector[:limit]

    async def text_search(self, book_id: UUID, query: str, limit: int) -> list[RetrievedChunk]:
        return self.by_text[:limit]


def test_rrf_ranks_items_in_both_lists_first() -> None:
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["c", "d", "a"]])
    assert [item for item, _ in fused] == ["a", "c", "b", "d"]


def test_rrf_of_nothing_is_empty() -> None:
    assert reciprocal_rank_fusion([[], []]) == []


async def test_merges_both_paths_without_duplicates() -> None:
    a, b, c = chunk("alpha"), chunk("beta"), chunk("gamma")
    retriever = HybridRetriever(StubSearcher([a, b], [b, c]), FakeEmbedder())
    result = await retriever.retrieve(uuid4(), "q")
    assert [r.id for r in result] == [b.id, a.id, c.id]


async def test_reranker_reorders_and_top_k_cuts() -> None:
    off = chunk("unrelated words here")
    on = chunk("sông Hồng chảy qua Hà Nội")
    retriever = HybridRetriever(StubSearcher([off, on], [off]), FakeEmbedder(), FakeReranker())
    result = await retriever.retrieve(uuid4(), "sông Hồng", top_k=1)
    assert [r.id for r in result] == [on.id]
    assert result[0].score == pytest.approx(1.0)
