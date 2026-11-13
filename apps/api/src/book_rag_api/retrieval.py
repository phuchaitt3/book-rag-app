import logging
import re
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Select, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from book_rag.retrieval import RetrievedChunk
from book_rag_api.lexical import BM25_SEARCH, K1, RARE_SHARE, B, has_stats
from book_rag_api.models import Chunk

log = logging.getLogger(__name__)

_WORD = re.compile(r"\w+")

# pgvector 0.8 added iterative index scans; the setting does not exist before that.
_ITERATIVE_SCAN_MIN_VERSION = (0, 8)


def supports_iterative_scan(version: str | None) -> bool:
    """Whether an `extversion` of pgvector (for example `0.8.0`, `0.8.0-dev`) is 0.8 or newer."""
    parts = tuple(int(p) for p in re.findall(r"\d+", version or "")[:2])
    return parts >= _ITERATIVE_SCAN_MIN_VERSION


def or_query(query: str) -> str:
    """A `to_tsquery` string matching any word of `query`; empty if it has no words.

    Words are cut to letters and digits, so user input cannot inject tsquery syntax.
    """
    return " | ".join(_WORD.findall(query))


class SqlChunkSearcher:
    """Searches the `chunks` table: pgvector cosine distance and Postgres full-text rank."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions
        self._iterative_scan: bool | None = None  # cached once the extension reports a version
        self._warned_missing = False

    async def vector_search(
        self, book_id: UUID, embedding: Sequence[float], limit: int
    ) -> list[RetrievedChunk]:
        stmt = (
            select(Chunk)
            .where(Chunk.book_id == book_id, Chunk.embedding.is_not(None))
            .order_by(Chunk.embedding.cosine_distance(list(embedding)))
            .limit(limit)
        )
        setup: list[str] = []
        if await self._supports_iterative_scan():
            # With a `book_id` filter the HNSW index alone can return few or no rows,
            # because it keeps only about `hnsw.ef_search` candidates before the filter.
            # The walk is bounded by `hnsw.max_scan_tuples` (20,000 by default), so it
            # covers today's corpus, not millions of chunks (see ADR 0002).
            setup.append("SET LOCAL hnsw.iterative_scan = strict_order")
        return await self._fetch(stmt, setup)

    async def text_search(self, book_id: UUID, query: str, limit: int) -> list[RetrievedChunk]:
        """BM25 over the book's stored statistics (ADR 0011).

        A book with no statistics (ingested before they existed and not backfilled) falls back
        to `ts_rank_cd`, which ranks worse but never returns nothing for that reason.
        """
        if not or_query(query):
            return []
        async with self._sessions() as session:
            if await has_stats(session, book_id):
                rows = await session.execute(
                    BM25_SEARCH,
                    {
                        "book_id": book_id,
                        "query": query,
                        "share": RARE_SHARE,
                        "k1": K1,
                        "b": B,
                        "limit": limit,
                    },
                )
                return [
                    RetrievedChunk(id=r.id, text=r.text, page=r.page, section_path=r.section_path)
                    for r in rows
                ]
        return await self._ts_rank_search(book_id, query, limit)

    async def _ts_rank_search(self, book_id: UUID, query: str, limit: int) -> list[RetrievedChunk]:
        tsquery = func.to_tsquery("simple", or_query(query))
        stmt = (
            select(Chunk)
            .where(Chunk.book_id == book_id, Chunk.tsv.op("@@")(tsquery))
            .order_by(func.ts_rank_cd(Chunk.tsv, tsquery).desc())
            .limit(limit)
        )
        return await self._fetch(stmt)

    async def _fetch(self, stmt: Select[Chunk], setup: Sequence[str] = ()) -> list[RetrievedChunk]:
        async with self._sessions() as session:
            for statement in setup:
                # `LOCAL` lasts for this transaction, so it also holds behind a pooler.
                await session.execute(text(statement))
            rows = await session.scalars(stmt)
            return [
                RetrievedChunk(id=c.id, text=c.text, page=c.page, section_path=c.section_path)
                for c in rows
            ]

    async def _supports_iterative_scan(self) -> bool:
        if self._iterative_scan is None:
            async with self._sessions() as session:
                version = await session.scalar(
                    text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
                )
            if version is None:
                # Not created yet: do not cache, ask again on the next search, warn once.
                if not self._warned_missing:
                    self._warned_missing = True
                    log.warning("pgvector is not installed; searching without iterative scan")
                return False
            self._iterative_scan = supports_iterative_scan(version)
            if not self._iterative_scan:
                log.warning(
                    "pgvector %s is older than 0.8; per-book vector search may return too few rows",
                    version,
                )
        return self._iterative_scan
