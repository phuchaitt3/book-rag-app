import asyncio
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID

from book_rag.providers.base import Embedder, Reranker
from book_rag.retrieval.fusion import reciprocal_rank_fusion
from book_rag.tracing import NoopTracer, SpanHandle, Tracer

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    id: UUID
    text: str
    page: int | None
    section_path: str | None
    # Fusion score, replaced by the reranker's score when a reranker is used.
    score: float = 0.0
    # True when `score` came from the reranker, False for the fused (RRF) score. The two scales
    # differ, so an abstain threshold is set for each (#222).
    reranked: bool = False


class ChunkSearcher(Protocol):
    """The two search paths over one book's chunks; each returns best match first.

    `owner_id` is required: a searcher returns only chunks of a book that owner owns, so a
    caller cannot search unscoped by leaving it out.
    """

    async def vector_search(
        self, book_id: UUID, embedding: Sequence[float], limit: int, *, owner_id: str
    ) -> list[RetrievedChunk]: ...

    async def text_search(
        self, book_id: UUID, query: str, limit: int, *, owner_id: str
    ) -> list[RetrievedChunk]: ...


class RetrievalObserver(Protocol):
    """Told how long each retrieval step took and when the reranker was skipped (ADR 0010).

    Steps are `embed`, `search` and `rerank`. The API turns these into metrics; this package
    names no metrics library.
    """

    def stage_done(self, stage: str, seconds: float) -> None: ...

    def retrieval_done(self, seconds: float) -> None: ...

    def rerank_fallback(self, reason: str) -> None: ...


def _fallback_reason(error: Exception) -> str:
    # urllib wraps a connect timeout in URLError(reason=TimeoutError).
    timed_out = isinstance(error, TimeoutError) or isinstance(
        getattr(error, "reason", None), TimeoutError
    )
    return "timeout" if timed_out else "error"


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
        observer: RetrievalObserver | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        if rerank_depth < 1:
            raise ValueError("rerank_depth must be positive")
        self._searcher = searcher
        self._embedder = embedder
        self._reranker = reranker
        self._candidates = candidates
        self._rerank_depth = rerank_depth
        self._observer = observer
        self._tracer: Tracer = tracer or NoopTracer()

    async def retrieve(
        self, book_id: UUID, query: str, *, owner_id: str, top_k: int = 8
    ) -> list[RetrievedChunk]:
        started = time.perf_counter()
        with self._tracer.span("embed_query", book_id=str(book_id)):
            [embedding] = await self._embedder.embed([query])
        embedded = time.perf_counter()
        by_vector, by_text = await asyncio.gather(
            self._vector_search(book_id, embedding, owner_id),
            self._lexical_search(book_id, query, owner_id),
        )
        searched = time.perf_counter()
        with self._tracer.span(
            "fuse",
            book_id=str(book_id),
            vector_candidates=len(by_vector),
            top_k=top_k,
            lexical_candidates=len(by_text),
        ) as span:
            chunks = {c.id: c for c in (*by_text, *by_vector)}
            fused = reciprocal_rank_fusion([[c.id for c in by_vector], [c.id for c in by_text]])
            merged = [replace(chunks[chunk_id], score=score) for chunk_id, score in fused]
            span.set_attribute("fused_candidates", len(merged))

        if self._reranker is not None and merged:
            merged = await self._rerank(self._reranker, query, merged, book_id)
        if self._observer is not None:
            self._observer.stage_done("embed", embedded - started)
            self._observer.stage_done("search", searched - embedded)
            self._observer.retrieval_done(time.perf_counter() - started)
        return merged[:top_k]

    async def _vector_search(
        self, book_id: UUID, embedding: Sequence[float], owner_id: str
    ) -> list[RetrievedChunk]:
        with self._tracer.span("vector_search", book_id=str(book_id), k=self._candidates) as span:
            found = await self._searcher.vector_search(
                book_id, embedding, self._candidates, owner_id=owner_id
            )
            span.set_attribute("candidates", len(found))
            return found

    async def _lexical_search(
        self, book_id: UUID, query: str, owner_id: str
    ) -> list[RetrievedChunk]:
        with self._tracer.span("lexical_search", book_id=str(book_id), k=self._candidates) as span:
            found = await self._searcher.text_search(
                book_id, query, self._candidates, owner_id=owner_id
            )
            span.set_attribute("candidates", len(found))
            return found

    async def _rerank(
        self, reranker: Reranker, query: str, fused: list[RetrievedChunk], book_id: UUID
    ) -> list[RetrievedChunk]:
        with self._tracer.span("rerank", book_id=str(book_id)) as span:
            return await self._rerank_traced(reranker, query, fused, span)

    async def _rerank_traced(
        self, reranker: Reranker, query: str, fused: list[RetrievedChunk], span: SpanHandle
    ) -> list[RetrievedChunk]:
        head, tail = fused[: self._rerank_depth], fused[self._rerank_depth :]
        span.set_attribute("candidates", len(head))
        span.set_attribute("fallback", False)
        started = time.perf_counter()
        try:
            scores = await reranker.rerank(query, [c.text for c in head])
            rescored = [
                replace(c, score=s, reranked=True) for c, s in zip(head, scores, strict=True)
            ]
        except Exception as error:
            # A slow or broken reranker should cost answer quality, not the answer.
            log.warning("reranker failed; using the fused order", exc_info=True)
            span.set_attribute("fallback", True)
            if self._observer is not None:
                self._observer.rerank_fallback(_fallback_reason(error))
            return fused
        finally:
            if self._observer is not None:
                self._observer.stage_done("rerank", time.perf_counter() - started)
        # The tail keeps its fused order after the reranked head; it is reached only when
        # top_k is larger than the depth.
        return sorted(rescored, key=lambda c: c.score, reverse=True) + tail
