import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID

from book_rag.providers.base import Embedder, Reranker
from book_rag.retrieval.fusion import reciprocal_rank_fusion


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    id: UUID
    text: str
    page: int | None
    section_path: str | None
    # Fusion score, replaced by the reranker's score when a reranker is used.
    score: float = 0.0


class ChunkSearcher(Protocol):
    """The two search paths over one book's chunks; each returns best match first."""

    async def vector_search(
        self, book_id: UUID, embedding: Sequence[float], limit: int
    ) -> list[RetrievedChunk]: ...

    async def text_search(self, book_id: UUID, query: str, limit: int) -> list[RetrievedChunk]: ...


class HybridRetriever:
    """Vector and full-text results merged with RRF, then reordered by a reranker."""

    def __init__(
        self,
        searcher: ChunkSearcher,
        embedder: Embedder,
        reranker: Reranker | None = None,
        candidates: int = 30,
    ) -> None:
        self._searcher = searcher
        self._embedder = embedder
        self._reranker = reranker
        self._candidates = candidates

    async def retrieve(self, book_id: UUID, query: str, top_k: int = 8) -> list[RetrievedChunk]:
        [embedding] = await self._embedder.embed([query])
        by_vector, by_text = await asyncio.gather(
            self._searcher.vector_search(book_id, embedding, self._candidates),
            self._searcher.text_search(book_id, query, self._candidates),
        )
        chunks = {c.id: c for c in (*by_text, *by_vector)}
        fused = reciprocal_rank_fusion([[c.id for c in by_vector], [c.id for c in by_text]])
        merged = [replace(chunks[chunk_id], score=score) for chunk_id, score in fused]

        if self._reranker is not None and merged:
            scores = await self._reranker.rerank(query, [c.text for c in merged])
            merged = sorted(
                (replace(c, score=s) for c, s in zip(merged, scores, strict=True)),
                key=lambda c: c.score,
                reverse=True,
            )
        return merged[:top_k]
