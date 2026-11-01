"""The Qdrant copy of the chunk vectors, for the experiment in ADR 0008.

Postgres stays the source of truth: this index holds only point id (= chunk id), the vector and
a `book_id` payload, and it can be rebuilt from `chunks`. EXPIRY 2026-12-15: delete this module,
the `VECTOR_STORE` setting and the Compose service, or promote it by a superseding ADR.
"""

import asyncio
import logging
import time
from collections.abc import Sequence
from uuid import UUID

from qdrant_client import AsyncQdrantClient, models
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from book_rag.retrieval import RetrievedChunk
from book_rag_api.models import EMBEDDING_DIM, Chunk
from book_rag_api.retrieval import SqlChunkSearcher

log = logging.getLogger(__name__)

_BOOK_ID = "book_id"


def _book_filter(book_id: UUID) -> models.Filter:
    return models.Filter(
        must=[models.FieldCondition(key=_BOOK_ID, match=models.MatchValue(value=str(book_id)))]
    )


class QdrantVectorIndex:
    def __init__(
        self, client: AsyncQdrantClient, collection: str, dimension: int = EMBEDDING_DIM
    ) -> None:
        self._client = client
        self._collection = collection
        self._dimension = dimension
        self._ready = False

    async def _ensure_collection(self) -> None:
        if self._ready:
            return
        if not await self._client.collection_exists(self._collection):
            await self._client.create_collection(
                self._collection,
                vectors_config=models.VectorParams(
                    size=self._dimension, distance=models.Distance.COSINE
                ),
            )
        # A tenant index keeps the vectors of one book together on disk, so a filtered search
        # touches one book's points. Local (in-memory) mode accepts and ignores it.
        await self._client.create_payload_index(
            self._collection,
            _BOOK_ID,
            field_schema=models.KeywordIndexParams(
                type=models.KeywordIndexType.KEYWORD, is_tenant=True
            ),
        )
        self._ready = True

    async def upsert(self, book_id: UUID, items: Sequence[tuple[UUID, Sequence[float]]]) -> None:
        """Insert or overwrite the points of one batch. Safe to repeat: same id, same vector."""
        await self._ensure_collection()
        await self._client.upsert(
            self._collection,
            points=[
                models.PointStruct(
                    id=str(chunk_id), vector=list(vector), payload={_BOOK_ID: str(book_id)}
                )
                for chunk_id, vector in items
            ],
            wait=True,
        )

    async def delete_book(self, book_id: UUID) -> None:
        await self._ensure_collection()
        await self._client.delete(
            self._collection,
            points_selector=models.FilterSelector(filter=_book_filter(book_id)),
            wait=True,
        )

    async def count(self, book_id: UUID) -> int:
        await self._ensure_collection()
        result = await self._client.count(
            self._collection, count_filter=_book_filter(book_id), exact=True
        )
        return result.count

    async def search(self, book_id: UUID, embedding: Sequence[float], limit: int) -> list[UUID]:
        """Chunk ids of the nearest points in one book, best first."""
        await self._ensure_collection()
        response = await self._client.query_points(
            self._collection,
            query=list(embedding),
            query_filter=_book_filter(book_id),
            limit=limit,
        )
        return [UUID(str(point.id)) for point in response.points]


class QdrantChunkSearcher:
    """Vector search in Qdrant, the chunk text from Postgres; keyword search is unchanged."""

    def __init__(
        self,
        index: QdrantVectorIndex,
        sessions: async_sessionmaker[AsyncSession],
        text_searcher: SqlChunkSearcher,
    ) -> None:
        self._index = index
        self._sessions = sessions
        self._text_searcher = text_searcher

    async def vector_search(
        self, book_id: UUID, embedding: Sequence[float], limit: int
    ) -> list[RetrievedChunk]:
        ids = await self._index.search(book_id, embedding, limit)
        if not ids:
            return []
        async with self._sessions() as session:
            rows = await session.scalars(select(Chunk).where(Chunk.id.in_(ids)))
            by_id = {
                c.id: RetrievedChunk(id=c.id, text=c.text, page=c.page, section_path=c.section_path)
                for c in rows
            }
        # Qdrant's order is the ranking; a point whose chunk is gone from Postgres is skipped.
        return [by_id[i] for i in ids if i in by_id]

    async def text_search(self, book_id: UUID, query: str, limit: int) -> list[RetrievedChunk]:
        return await self._text_searcher.text_search(book_id, query, limit)


class ShadowChunkSearcher:
    """Returns the Postgres result and, in the background, compares it with Qdrant's.

    One log line per search: the overlap of the two result lists and the time each took
    (`vector_search shadow ...`). An error on the Qdrant path is logged and never reaches the
    caller. The Qdrant search starts after the Postgres one returned, so the two timings do not
    disturb each other.
    """

    def __init__(self, primary: SqlChunkSearcher, shadow: QdrantChunkSearcher) -> None:
        self._primary = primary
        self._shadow = shadow
        self._tasks: set[asyncio.Task[None]] = set()  # keeps the tasks alive until they finish

    async def vector_search(
        self, book_id: UUID, embedding: Sequence[float], limit: int
    ) -> list[RetrievedChunk]:
        started = time.perf_counter()
        result = await self._primary.vector_search(book_id, embedding, limit)
        primary_ms = (time.perf_counter() - started) * 1000
        task = asyncio.create_task(self._compare(book_id, embedding, limit, result, primary_ms))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return result

    async def _compare(
        self,
        book_id: UUID,
        embedding: Sequence[float],
        limit: int,
        expected: list[RetrievedChunk],
        primary_ms: float,
    ) -> None:
        try:
            started = time.perf_counter()
            found = await self._shadow.vector_search(book_id, embedding, limit)
            shadow_ms = (time.perf_counter() - started) * 1000
        except Exception:
            log.exception("vector_search shadow: the Qdrant search failed (book %s)", book_id)
            return
        overlap = len({c.id for c in expected} & {c.id for c in found})
        log.info(
            "vector_search shadow book=%s limit=%d overlap=%d/%d pgvector_ms=%.1f qdrant_ms=%.1f",
            book_id,
            limit,
            overlap,
            len(expected),
            primary_ms,
            shadow_ms,
        )

    async def text_search(self, book_id: UUID, query: str, limit: int) -> list[RetrievedChunk]:
        return await self._primary.text_search(book_id, query, limit)


async def vector_counts(
    sessions: async_sessionmaker[AsyncSession], index: QdrantVectorIndex, book_id: UUID
) -> tuple[int, int]:
    """(chunks with an embedding in Postgres, points in Qdrant) for one book; equal when in step."""
    async with sessions() as session:
        in_postgres = await session.scalar(
            select(func.count())
            .select_from(Chunk)
            .where(Chunk.book_id == book_id, Chunk.embedding.is_not(None))
        )
    return in_postgres or 0, await index.count(book_id)
