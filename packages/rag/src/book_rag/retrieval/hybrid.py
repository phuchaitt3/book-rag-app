import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID

from book_rag.providers.base import Embedder, Reranker
from book_rag.retrieval.fusion import reciprocal_rank_fusion

log = logging.getLogger(__name__)


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
    """Vector and full-text results merged with RRF, then the top `rerank_depth` reordered by a
    reranker. If the reranker fails or times out, the fused order is returned (ADR 0009)."""

    def __init__(
        self,
        searcher: ChunkSearcher,
        embedder: Embedder,
        reranker: Reranker | None = None,
        candidates: int = 30,
        rerank_depth: int = 20,
    ) -> None:
        if rerank_depth < 1:
            raise ValueError("rerank_depth must be positive")
        self._searcher = searcher
        self._embedder = embedder
        self._reranker = reranker
        self._candidates = candidates
        self._rerank_depth = rerank_depth

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
            merged = await self._rerank(self._reranker, query, merged)
        return merged[:top_k]

    async def _rerank(
        self, reranker: Reranker, query: str, fused: list[RetrievedChunk]
    ) -> list[RetrievedChunk]:
        head, tail = fused[: self._rerank_depth], fused[self._rerank_depth :]
        try:
            scores = await reranker.rerank(query, [c.text for c in head])
            rescored = [replace(c, score=s) for c, s in zip(head, scores, strict=True)]
        except Exception:
            # A slow or broken reranker should cost answer quality, not the answer.
            log.warning("reranker failed; using the fused order", exc_info=True)
            return fused
        # The tail keeps its fused order after the reranked head; it is reached only when
        # top_k is larger than the depth.
        return sorted(rescored, key=lambda c: c.score, reverse=True) + tail
