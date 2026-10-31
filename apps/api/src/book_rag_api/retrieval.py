import re
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from book_rag.retrieval import RetrievedChunk
from book_rag_api.models import Chunk

_WORD = re.compile(r"\w+")


def or_query(text: str) -> str:
    """A `to_tsquery` string matching any word of `text`; empty if it has no words.

    Words are cut to letters and digits, so user input cannot inject tsquery syntax.
    """
    return " | ".join(_WORD.findall(text))


class SqlChunkSearcher:
    """Searches the `chunks` table: pgvector cosine distance and Postgres full-text rank."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def vector_search(
        self, book_id: UUID, embedding: Sequence[float], limit: int
    ) -> list[RetrievedChunk]:
        stmt = (
            select(Chunk)
            .where(Chunk.book_id == book_id, Chunk.embedding.is_not(None))
            .order_by(Chunk.embedding.cosine_distance(list(embedding)))
            .limit(limit)
        )
        return await self._fetch(stmt)

    async def text_search(self, book_id: UUID, query: str, limit: int) -> list[RetrievedChunk]:
        tsquery_text = or_query(query)
        if not tsquery_text:
            return []
        tsquery = func.to_tsquery("simple", tsquery_text)
        stmt = (
            select(Chunk)
            .where(Chunk.book_id == book_id, Chunk.tsv.op("@@")(tsquery))
            .order_by(func.ts_rank_cd(Chunk.tsv, tsquery).desc())
            .limit(limit)
        )
        return await self._fetch(stmt)

    async def _fetch(self, stmt: Select[Chunk]) -> list[RetrievedChunk]:
        async with self._sessions() as session:
            rows = await session.scalars(stmt)
            return [
                RetrievedChunk(id=c.id, text=c.text, page=c.page, section_path=c.section_path)
                for c in rows
            ]
