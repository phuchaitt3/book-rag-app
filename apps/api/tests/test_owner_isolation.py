"""User A cannot list, read, chat with, delete or poll user B's book (#230).

Another owner's book is 404, never 403, so a caller cannot tell it from a book that does not
exist. Needs Docker (a Postgres container), like the other database tests.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import procrastinate
import pytest
from httpx import ASGITransport, AsyncClient
from procrastinate import testing
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from test_books import FakeStorage, make_pdf
from test_chat import database_url, event_loop_policy  # noqa: F401

from book_rag.providers import FakeEmbedder, FakeLLM
from book_rag_api.auth import DEV_USER_HEADER
from book_rag_api.config import Settings
from book_rag_api.lexical import refresh_book_stats
from book_rag_api.main import create_app
from book_rag_api.models import EMBEDDING_DIM, Book, Chunk, IngestionJob
from book_rag_api.retrieval import SqlChunkSearcher

TEXTS = ["Sông Hồng chảy qua Hà Nội", "Núi Fansipan cao nhất Đông Dương"]


@dataclass
class World:
    a: AsyncClient
    b: AsyncClient
    storage: FakeStorage
    database_url: str
    a_book: UUID
    b_book: UUID
    a_job: UUID
    b_job: UUID
    owner_a: str
    owner_b: str


async def seed(engine_url: str, owner: str) -> tuple[UUID, UUID]:
    engine = create_async_engine(engine_url)
    vectors = await FakeEmbedder(EMBEDDING_DIM).embed(TEXTS)
    book = Book(id=uuid4(), title=f"book of {owner}", owner_id=owner, storage_key=f"k/{owner}.pdf")
    job = IngestionJob(book_id=book.id, status="succeeded")
    async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
        session.add(book)
        await session.flush()
        session.add_all(
            Chunk(book_id=book.id, ordinal=i, text=t, page=i + 1, embedding=v)
            for i, (t, v) in enumerate(zip(TEXTS, vectors, strict=True))
        )
        session.add(job)
        await session.flush()
        await refresh_book_stats(session, book.id)
        job_id = job.id
    await engine.dispose()
    return book.id, job_id


@pytest.fixture
async def world(database_url: str) -> AsyncIterator[World]:  # noqa: F811
    owner_a, owner_b = f"a-{uuid4()}", f"b-{uuid4()}"
    a_book, a_job = await seed(database_url, owner_a)
    b_book, b_job = await seed(database_url, owner_b)
    storage = FakeStorage()
    app = create_app(
        Settings(database_url=database_url),
        storage=storage,
        queue=procrastinate.App(connector=testing.InMemoryConnector()),
        llm=FakeLLM("ok [1]"),
        embedder=FakeEmbedder(EMBEDDING_DIM),
    )
    transport = ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=transport, base_url="http://test", headers={DEV_USER_HEADER: owner_a}
        ) as a,
        AsyncClient(
            transport=transport, base_url="http://test", headers={DEV_USER_HEADER: owner_b}
        ) as b,
    ):
        yield World(a, b, storage, database_url, a_book, b_book, a_job, b_job, owner_a, owner_b)


async def test_list_shows_only_the_callers_books(world: World) -> None:
    listed_a = {b["id"] for b in (await world.a.get("/books")).json()}
    listed_b = {b["id"] for b in (await world.b.get("/books")).json()}
    assert listed_a == {str(world.a_book)}
    assert listed_b == {str(world.b_book)}


async def test_read_is_404_for_another_owner_and_the_same_as_a_missing_book(
    world: World,
) -> None:
    assert (await world.b.get(f"/books/{world.b_book}")).status_code == 200
    other = await world.a.get(f"/books/{world.b_book}")
    missing = await world.a.get(f"/books/{uuid4()}")
    assert other.status_code == missing.status_code == 404
    assert other.json()["detail"] == missing.json()["detail"]


async def test_chat_with_another_owners_book_is_404(world: World) -> None:
    mine = await world.b.post(f"/books/{world.b_book}/chat", json={"question": "sông Hồng"})
    assert mine.status_code == 200
    other = await world.a.post(f"/books/{world.b_book}/chat", json={"question": "sông Hồng"})
    missing = await world.a.post(f"/books/{uuid4()}/chat", json={"question": "sông Hồng"})
    assert other.status_code == missing.status_code == 404
    assert other.json()["detail"] == missing.json()["detail"]
    assert "Hồng" not in other.text


async def test_delete_of_another_owners_book_is_404_and_changes_nothing(world: World) -> None:
    refused = await world.a.delete(f"/books/{world.b_book}")
    assert refused.status_code == 404
    assert (await world.b.get(f"/books/{world.b_book}")).status_code == 200
    assert (await world.b.delete(f"/books/{world.b_book}")).status_code == 204
    assert (await world.b.get(f"/books/{world.b_book}")).status_code == 404
    # The owner's other data is untouched.
    assert (await world.a.get(f"/books/{world.a_book}")).status_code == 200


async def test_delete_removes_the_stored_pdf(world: World) -> None:
    world.storage.objects[f"k/{world.owner_b}.pdf"] = b"%PDF-"
    assert (await world.a.delete(f"/books/{world.b_book}")).status_code == 404
    assert world.storage.objects != {}
    assert (await world.b.delete(f"/books/{world.b_book}")).status_code == 204
    assert world.storage.objects == {}


async def test_job_status_is_404_for_another_owner(world: World) -> None:
    assert (await world.b.get(f"/ingestion-jobs/{world.b_job}")).status_code == 200
    other = await world.a.get(f"/ingestion-jobs/{world.b_job}")
    missing = await world.a.get(f"/ingestion-jobs/{uuid4()}")
    assert other.status_code == missing.status_code == 404
    assert other.json()["detail"] == missing.json()["detail"]


async def test_an_upload_belongs_to_the_uploader(world: World) -> None:
    uploaded = await world.a.post(
        "/books", files={"file": ("x.pdf", make_pdf(1), "application/pdf")}, data={"title": "N"}
    )
    assert uploaded.status_code == 201
    new_id = uploaded.json()["book"]["id"]
    assert new_id in {b["id"] for b in (await world.a.get("/books")).json()}
    assert new_id not in {b["id"] for b in (await world.b.get("/books")).json()}
    job_id = uploaded.json()["job_id"]
    assert (await world.b.get(f"/ingestion-jobs/{job_id}")).status_code == 404
    assert (await world.a.get(f"/ingestion-jobs/{job_id}")).status_code == 200


async def test_retrieval_sql_returns_nothing_for_another_owners_book(world: World) -> None:
    engine = create_async_engine(world.database_url)
    searcher = SqlChunkSearcher(async_sessionmaker(engine, expire_on_commit=False))
    [vector] = await FakeEmbedder(EMBEDDING_DIM).embed([TEXTS[0]])
    try:
        # The owner finds the passages, by BM25 and by vector.
        assert await searcher.text_search([world.b_book], "Hà Nội", 5, owner_id=world.owner_b)
        assert await searcher.vector_search([world.b_book], vector, 5, owner_id=world.owner_b)
        # Anyone else gets none, through the same SQL.
        assert await searcher.text_search([world.b_book], "Hà Nội", 5, owner_id=world.owner_a) == []
        assert await searcher.vector_search([world.b_book], vector, 5, owner_id=world.owner_a) == []
        assert await searcher.text_search([world.b_book], "Hà Nội", 5, owner_id="nobody") == []
    finally:
        await engine.dispose()


async def test_mcp_tools_are_scoped_to_their_owner(world: World) -> None:
    from mcp.server.mcpserver.exceptions import ToolError

    from book_rag.providers import FakeReranker
    from book_rag.retrieval import HybridRetriever
    from book_rag_api.mcp_server import BookIndex

    engine = create_async_engine(world.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    retriever = HybridRetriever(
        SqlChunkSearcher(sessions), FakeEmbedder(EMBEDDING_DIM), FakeReranker()
    )
    mine = BookIndex(sessions, retriever, owner_id=world.owner_b, retrieval_timeout=10)
    theirs = BookIndex(sessions, retriever, owner_id=world.owner_a, retrieval_timeout=10)
    try:
        found = await mine.search_book("Hà Nội", str(world.b_book), 3)
        assert found.passages
        chunk_id = found.passages[0].chunk_id
        assert (await mine.get_passage(str(chunk_id), 0)).passage.chunk_id == chunk_id
        with pytest.raises(ToolError, match="no book"):
            await theirs.search_book("Hà Nội", str(world.b_book), 3)
        with pytest.raises(ToolError, match="no passage"):
            await theirs.get_passage(str(chunk_id), 0)
        with pytest.raises(ToolError, match="no passage"):
            await theirs.cite([str(chunk_id)])
    finally:
        await engine.dispose()
