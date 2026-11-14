"""An MCP server over the book index (#242): `search_book`, `get_passage` and `cite`.

It runs over stdio, so an MCP client (an agent, an editor) starts it as a subprocess:

  uv run python -m book_rag_api.mcp_server

Search goes through the same `HybridRetriever` the chat endpoint uses (`build_retriever`), so
an agent sees the ranking a chat answer is built from. The tools return typed JSON (each
return type is a pydantic model, so the client gets an output schema); a bad request (an empty
query, an unknown id) is an error result with a message, not a crash.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from book_rag.retrieval import HybridRetriever, RetrievedChunk
from book_rag_api.config import Settings, get_settings
from book_rag_api.db import create_engine
from book_rag_api.main import build_retriever
from book_rag_api.models import Book, Chunk, IngestionJob

log = logging.getLogger(__name__)

MAX_K = 20
MAX_CONTEXT = 5
MAX_CITE = 50
MAX_QUERY_CHARS = 2000


class Passage(BaseModel):
    chunk_id: uuid.UUID
    book_id: uuid.UUID
    section: str | None
    page: int | None
    text: str


class SearchHit(Passage):
    score: float = Field(description="Relevance, higher is better; comparable within one search")


class SearchResult(BaseModel):
    book_id: uuid.UUID
    book_title: str
    query: str
    passages: list[SearchHit]


class PassageResult(BaseModel):
    """The requested chunk, and its neighbours in book order when `context` was set."""

    passage: Passage
    before: list[Passage]
    after: list[Passage]


class Citation(BaseModel):
    chunk_id: uuid.UUID
    book_title: str
    section: str | None
    page: int | None
    citation: str = Field(description="Ready-to-print text, e.g. 'Title, Section, p. 12'")


class CiteResult(BaseModel):
    citations: list[Citation]


def format_citation(title: str, section: str | None, page: int | None) -> str:
    parts = [title]
    if section:
        parts.append(section)
    if page is not None:
        parts.append(f"p. {page}")
    return ", ".join(parts)


def _passage(chunk: Chunk) -> Passage:
    return Passage(
        chunk_id=chunk.id,
        book_id=chunk.book_id,
        section=chunk.section_path,
        page=chunk.page,
        text=chunk.text,
    )


def _hit(book_id: uuid.UUID, chunk: RetrievedChunk) -> SearchHit:
    return SearchHit(
        chunk_id=chunk.id,
        book_id=book_id,
        section=chunk.section_path,
        page=chunk.page,
        text=chunk.text,
        score=chunk.score,
    )


def _parse_id(value: str, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise ToolError(f"{what} {value!r} is not a valid id") from None


class BookIndex:
    """The three tools' logic, apart from the MCP plumbing so it is plain to test."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        retriever: HybridRetriever,
        *,
        retrieval_timeout: float = 30.0,
    ) -> None:
        self._sessions = sessions
        self._retriever = retriever
        self._timeout = retrieval_timeout

    async def search_book(self, query: str, book_id: str | None, k: int) -> SearchResult:
        query = query.strip()
        if not query:
            raise ToolError("query is empty; give the words to search for")
        if len(query) > MAX_QUERY_CHARS:
            raise ToolError(f"query is longer than {MAX_QUERY_CHARS} characters")
        if not 1 <= k <= MAX_K:
            raise ToolError(f"k must be between 1 and {MAX_K}")
        book = await self._book(book_id)
        try:
            async with asyncio.timeout(self._timeout):
                chunks = await self._retriever.retrieve(book.id, query, top_k=k)
        except Exception:
            log.exception("retrieval failed")
            raise ToolError("search is unavailable; try again") from None
        return SearchResult(
            book_id=book.id,
            book_title=book.title,
            query=query,
            passages=[_hit(book.id, c) for c in chunks],
        )

    async def get_passage(self, chunk_id: str, context: int) -> PassageResult:
        if not 0 <= context <= MAX_CONTEXT:
            raise ToolError(f"context must be between 0 and {MAX_CONTEXT}")
        wanted = _parse_id(chunk_id, "chunk_id")
        async with self._sessions() as session:
            chunk = await session.get(Chunk, wanted)
            if chunk is None:
                raise ToolError(f"no passage with chunk_id {chunk_id}")
            before: list[Chunk] = []
            after: list[Chunk] = []
            if context:
                # By position, not by ordinal value: ordinals may have gaps.
                near = select(Chunk).where(Chunk.book_id == chunk.book_id).limit(context)
                before = list(
                    await session.scalars(
                        near.where(Chunk.ordinal < chunk.ordinal).order_by(Chunk.ordinal.desc())
                    )
                )
                before.reverse()
                after = list(
                    await session.scalars(
                        near.where(Chunk.ordinal > chunk.ordinal).order_by(Chunk.ordinal)
                    )
                )
        return PassageResult(
            passage=_passage(chunk),
            before=[_passage(c) for c in before],
            after=[_passage(c) for c in after],
        )

    async def cite(self, chunk_ids: list[str]) -> CiteResult:
        if not chunk_ids:
            raise ToolError("chunk_ids is empty")
        if len(chunk_ids) > MAX_CITE:
            raise ToolError(f"at most {MAX_CITE} chunk_ids per call")
        wanted = [_parse_id(c, "chunk_id") for c in chunk_ids]
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(Chunk.id, Chunk.section_path, Chunk.page, Book.title)
                    .join(Book, Book.id == Chunk.book_id)
                    .where(Chunk.id.in_(wanted))
                )
            ).all()
        found = {r.id: r for r in rows}
        missing = [str(w) for w in wanted if w not in found]
        if missing:
            raise ToolError(f"no passage with chunk_id {', '.join(missing)}")
        return CiteResult(
            citations=[
                Citation(
                    chunk_id=w,
                    book_title=found[w].title,
                    section=found[w].section_path,
                    page=found[w].page,
                    citation=format_citation(found[w].title, found[w].section_path, found[w].page),
                )
                for w in wanted
            ]
        )

    async def _book(self, book_id: str | None) -> Book:
        """The named book, or the only one when there is just one. It must be fully ingested
        (the chat endpoint's rule, ADR 0004)."""
        async with self._sessions() as session:
            if book_id is None:
                books = list(await session.scalars(select(Book).order_by(Book.created_at).limit(2)))
                if not books:
                    raise ToolError("there are no books in the index")
                if len(books) > 1:
                    raise ToolError("book_id is required: the index holds more than one book")
                book = books[0]
            else:
                found = await session.get(Book, _parse_id(book_id, "book_id"))
                if found is None:
                    raise ToolError(f"no book with book_id {book_id}")
                book = found
            latest = await session.scalar(
                select(IngestionJob.status)
                .where(IngestionJob.book_id == book.id)
                .order_by(IngestionJob.created_at.desc())
                .limit(1)
            )
        if latest is not None and latest != "succeeded":
            raise ToolError(f"the book is not ready yet: its ingestion is {latest}")
        return book


def create_server(index: BookIndex) -> MCPServer:
    server = MCPServer(
        "book-rag",
        instructions=(
            "Search a book and cite it. Call search_book to find passages, get_passage to read "
            "one in full with its neighbours, and cite to format citations for the chunk ids "
            "you rely on."
        ),
    )

    @server.tool()
    async def search_book(
        query: Annotated[str, Field(description="Words or a question to look for")],
        book_id: Annotated[
            str | None, Field(description="Book id; may be left out when the index has one book")
        ] = None,
        k: Annotated[int, Field(description=f"How many passages, 1 to {MAX_K}")] = 5,
    ) -> SearchResult:
        """Hybrid (vector and keyword) search of a book; returns the best passages first."""
        return await index.search_book(query, book_id, k)

    @server.tool()
    async def get_passage(
        chunk_id: Annotated[str, Field(description="A chunk_id from search_book")],
        context: Annotated[
            int, Field(description=f"Neighbouring passages each side, 0 to {MAX_CONTEXT}")
        ] = 0,
    ) -> PassageResult:
        """One passage in full, optionally with the passages before and after it."""
        return await index.get_passage(chunk_id, context)

    @server.tool()
    async def cite(
        chunk_ids: Annotated[list[str], Field(description="chunk_ids to cite, in order")],
    ) -> CiteResult:
        """Formatted citations (book title, section, page) for passages."""
        return await index.cite(chunk_ids)

    return server


async def serve(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    engine = create_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    retriever, vector_index = build_retriever(settings, sessions)
    try:
        index = BookIndex(sessions, retriever, retrieval_timeout=settings.retrieval_timeout)
        await create_server(index).run_stdio_async()
    finally:
        if vector_index is not None:
            await vector_index.close()
        await engine.dispose()


def main() -> None:
    # stdout carries the protocol, so logs go to stderr (the default handler).
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve())


if __name__ == "__main__":
    main()
