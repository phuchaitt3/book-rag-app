"""The MCP server (#242) driven by an in-process MCP client over the fake providers.

The book is the mini-book fixture; the database is the Postgres container the chat tests use.
No network, no GPU, no model. Each test's book is deleted afterwards, so a test sees only its own.
"""

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from mcp.client import Client
from mcp.server.mcpserver import MCPServer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from test_chat import database_url, event_loop_policy  # noqa: F401

from book_rag.providers import FakeEmbedder, FakeReranker
from book_rag.retrieval import HybridRetriever
from book_rag_api.mcp_server import BookIndex, create_server, format_citation
from book_rag_api.models import EMBEDDING_DIM, Book, Chunk, IngestionJob
from book_rag_api.retrieval import SqlChunkSearcher

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = json.loads((ROOT / "evals" / "fixtures" / "mini-book.json").read_text(encoding="utf-8"))
BAD_ID = "00000000-0000-4000-8000-000000000000"


@pytest.fixture
async def book(database_url: str) -> AsyncIterator[tuple[UUID, list[UUID]]]:  # noqa: F811
    """A fresh book from the fixture (pages 10, 11, ...) and its chunk ids in book order."""
    engine = create_async_engine(database_url)
    chunks = FIXTURE["chunks"]
    vectors = await FakeEmbedder(EMBEDDING_DIM).embed([c["text"] for c in chunks])
    book = Book(id=uuid4(), title=FIXTURE["book_title"])
    async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
        session.add(book)
        await session.flush()
        session.add_all(
            Chunk(
                book_id=book.id,
                ordinal=c["ordinal"],
                text=c["text"],
                page=10 + i,
                section_path=c["section_path"],
                embedding=v,
            )
            for i, (c, v) in enumerate(zip(chunks, vectors, strict=True))
        )
    async with AsyncSession(engine) as session:
        ids = list(
            await session.scalars(
                select(Chunk.id).where(Chunk.book_id == book.id).order_by(Chunk.ordinal)
            )
        )
    yield book.id, ids
    async with AsyncSession(engine) as session, session.begin():
        row = await session.get(Book, book.id)
        assert row is not None
        await session.delete(row)
    await engine.dispose()


@pytest.fixture
async def mcp(database_url: str) -> AsyncIterator[MCPServer]:  # noqa: F811
    """The server; each call below opens an in-process client on it (the client's task group
    cannot span a pytest-asyncio fixture's setup and teardown)."""
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    retriever = HybridRetriever(
        SqlChunkSearcher(sessions), FakeEmbedder(EMBEDDING_DIM), FakeReranker()
    )
    index = BookIndex(sessions, retriever, retrieval_timeout=10)
    yield create_server(index)
    await engine.dispose()


async def call(mcp: MCPServer, tool: str, **arguments: Any) -> Any:
    async with Client(mcp) as client:
        result = await client.call_tool(tool, arguments)
    assert not result.is_error, result.content
    return result.structured_content


async def error_of(mcp: MCPServer, tool: str, **arguments: Any) -> str:
    async with Client(mcp) as client:
        result = await client.call_tool(tool, arguments)
    assert result.is_error
    return " ".join(getattr(block, "text", "") for block in result.content)


async def test_lists_the_three_tools_with_schemas(mcp: MCPServer) -> None:
    async with Client(mcp) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}

    assert set(tools) == {"search_book", "get_passage", "cite"}
    assert tools["search_book"].input_schema["required"] == ["query"]
    assert set(tools["search_book"].input_schema["properties"]) == {"query", "book_id", "k"}
    assert tools["get_passage"].input_schema["required"] == ["chunk_id"]
    assert tools["cite"].input_schema["required"] == ["chunk_ids"]
    assert all(t.output_schema for t in tools.values())


async def test_search_book_returns_ranked_passages(
    mcp: MCPServer, book: tuple[UUID, list[UUID]]
) -> None:
    book_id, ids = book
    query = FIXTURE["chunks"][0]["text"][:120]

    out = await call(mcp, "search_book", query=query, book_id=str(book_id), k=3)

    assert out["book_id"] == str(book_id)
    assert out["book_title"] == FIXTURE["book_title"]
    hits = out["passages"]
    assert 1 <= len(hits) <= 3
    assert hits[0]["chunk_id"] == str(ids[0])  # the chunk the query was cut from ranks first
    assert hits[0]["section"] == FIXTURE["chunks"][0]["section_path"]
    assert hits[0]["page"] == 10
    assert hits[0]["text"] == FIXTURE["chunks"][0]["text"]
    assert [h["score"] for h in hits] == sorted((h["score"] for h in hits), reverse=True)


async def test_search_book_without_book_id_uses_the_only_book(
    mcp: MCPServer, book: tuple[UUID, list[UUID]]
) -> None:
    out = await call(mcp, "search_book", query="sử")

    assert out["book_id"] == str(book[0])


async def test_search_book_with_two_books_needs_a_book_id(
    mcp: MCPServer,
    book: tuple[UUID, list[UUID]],
    database_url: str,  # noqa: F811
) -> None:
    engine = create_async_engine(database_url)
    extra = Book(id=uuid4(), title="Another")
    async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
        session.add(extra)
    try:
        assert "book_id is required" in await error_of(mcp, "search_book", query="sử")
    finally:
        async with AsyncSession(engine) as session, session.begin():
            row = await session.get(Book, extra.id)
            assert row is not None
            await session.delete(row)
        await engine.dispose()


async def test_search_book_with_no_books_says_so(mcp: MCPServer) -> None:
    assert "no books" in await error_of(mcp, "search_book", query="sử")


@pytest.mark.parametrize("query", ["", "   \n"])
async def test_search_book_rejects_an_empty_query(
    mcp: MCPServer, book: tuple[UUID, list[UUID]], query: str
) -> None:
    assert "query is empty" in await error_of(mcp, "search_book", query=query, book_id=str(book[0]))


@pytest.mark.parametrize("k", [0, 21])
async def test_search_book_rejects_k_out_of_range(
    mcp: MCPServer, book: tuple[UUID, list[UUID]], k: int
) -> None:
    assert "k must be between" in await error_of(
        mcp, "search_book", query="sử", book_id=str(book[0]), k=k
    )


async def test_search_book_unknown_and_malformed_book_id(mcp: MCPServer) -> None:
    assert "no book with book_id" in await error_of(mcp, "search_book", query="sử", book_id=BAD_ID)
    assert "not a valid id" in await error_of(mcp, "search_book", query="sử", book_id="nope")


async def test_search_book_refuses_a_book_still_being_ingested(
    mcp: MCPServer,
    book: tuple[UUID, list[UUID]],
    database_url: str,  # noqa: F811
) -> None:
    book_id, _ = book
    engine = create_async_engine(database_url)
    async with AsyncSession(engine) as session, session.begin():
        session.add(IngestionJob(book_id=book_id, status="running"))
    await engine.dispose()

    assert "not ready yet" in await error_of(mcp, "search_book", query="sử", book_id=str(book_id))


async def test_get_passage_returns_one_chunk(mcp: MCPServer, book: tuple[UUID, list[UUID]]) -> None:
    book_id, ids = book

    out = await call(mcp, "get_passage", chunk_id=str(ids[1]))

    assert out["passage"]["chunk_id"] == str(ids[1])
    assert out["passage"]["book_id"] == str(book_id)
    assert out["passage"]["text"] == FIXTURE["chunks"][1]["text"]
    assert out["passage"]["page"] == 11
    assert out["before"] == [] and out["after"] == []


async def test_get_passage_with_context_returns_neighbours_in_order(
    mcp: MCPServer, book: tuple[UUID, list[UUID]]
) -> None:
    _, ids = book

    out = await call(mcp, "get_passage", chunk_id=str(ids[2]), context=2)

    assert [p["chunk_id"] for p in out["before"]] == [str(ids[0]), str(ids[1])]
    assert [p["chunk_id"] for p in out["after"]] == [str(i) for i in ids[3:5]]
    edge = await call(mcp, "get_passage", chunk_id=str(ids[0]), context=1)
    assert edge["before"] == []
    assert [p["chunk_id"] for p in edge["after"]] == [str(ids[1])]


async def test_get_passage_errors(mcp: MCPServer) -> None:
    assert "no passage with chunk_id" in await error_of(mcp, "get_passage", chunk_id=BAD_ID)
    assert "not a valid id" in await error_of(mcp, "get_passage", chunk_id="nope")
    assert "context must be between" in await error_of(
        mcp, "get_passage", chunk_id=BAD_ID, context=6
    )
    assert "context must be between" in await error_of(
        mcp, "get_passage", chunk_id=BAD_ID, context=-1
    )


async def test_cite_formats_citations_in_the_order_given(
    mcp: MCPServer, book: tuple[UUID, list[UUID]]
) -> None:
    _, ids = book
    title = FIXTURE["book_title"]
    section = FIXTURE["chunks"][1]["section_path"]

    out = await call(mcp, "cite", chunk_ids=[str(ids[1]), str(ids[0])])

    citations = out["citations"]
    assert [c["chunk_id"] for c in citations] == [str(ids[1]), str(ids[0])]
    assert citations[0]["citation"] == f"{title}, {section}, p. 11"
    assert citations[0]["book_title"] == title
    assert citations[0]["page"] == 11


async def test_cite_errors(mcp: MCPServer, book: tuple[UUID, list[UUID]]) -> None:
    _, ids = book

    assert "chunk_ids is empty" in await error_of(mcp, "cite", chunk_ids=[])
    assert "not a valid id" in await error_of(mcp, "cite", chunk_ids=["nope"])
    assert BAD_ID in await error_of(mcp, "cite", chunk_ids=[str(ids[0]), BAD_ID])
    assert "at most" in await error_of(mcp, "cite", chunk_ids=[BAD_ID] * 51)


async def test_a_search_hit_round_trips_through_get_passage_and_cite(
    mcp: MCPServer, book: tuple[UUID, list[UUID]]
) -> None:
    book_id, _ = book
    found = await call(mcp, "search_book", query="Tựa sử", book_id=str(book_id), k=1)
    hit = found["passages"][0]

    passage = await call(mcp, "get_passage", chunk_id=hit["chunk_id"])
    cited = await call(mcp, "cite", chunk_ids=[hit["chunk_id"]])

    assert passage["passage"]["text"] == hit["text"]
    assert cited["citations"][0]["chunk_id"] == hit["chunk_id"]


def test_format_citation_leaves_out_what_is_missing() -> None:
    assert format_citation("T", "S", 3) == "T, S, p. 3"
    assert format_citation("T", None, 3) == "T, p. 3"
    assert format_citation("T", "S", None) == "T, S"
    assert format_citation("T", None, None) == "T"
