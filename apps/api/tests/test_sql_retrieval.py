import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from qdrant_client import AsyncQdrantClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from book_rag.providers import FakeEmbedder, FakeReranker
from book_rag.retrieval import HybridRetriever
from book_rag_api.models import EMBEDDING_DIM, Book, Chunk
from book_rag_api.qdrant_index import QdrantChunkSearcher, QdrantVectorIndex, vector_counts
from book_rag_api.retrieval import SqlChunkSearcher, or_query, supports_iterative_scan

ALEMBIC_INI = Path(__file__).parents[1] / "alembic.ini"

TEXTS = [
    "Sông Hồng chảy qua Hà Nội",
    "Núi Fansipan cao nhất Đông Dương",
    "Hà Nội là thủ đô của Việt Nam",
]


def test_or_query_keeps_only_words() -> None:
    assert or_query("sông Hồng: 'Hà Nội' & !x") == "sông | Hồng | Hà | Nội | x"
    assert or_query("?! &") == ""


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("0.8.0", True),
        ("0.8.0-dev", True),
        ("0.10.1", True),
        ("1.0.0", True),
        ("0.7.4", False),
        ("0.7", False),
        ("", False),
        (None, False),
    ],
)
def test_iterative_scan_needs_pgvector_0_8(version: str | None, expected: bool) -> None:
    assert supports_iterative_scan(version) is expected


class _StubSession:
    """A session with no `vector` extension row and no chunks."""

    async def __aenter__(self) -> "_StubSession":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def scalar(self, _stmt: object) -> None:
        return None

    async def scalars(self, _stmt: object) -> list[Chunk]:
        return []


async def test_missing_pgvector_warns_once_and_is_asked_again(
    caplog: pytest.LogCaptureFixture,
) -> None:
    searcher = SqlChunkSearcher(lambda: _StubSession())  # type: ignore[arg-type]
    with caplog.at_level("WARNING", logger="book_rag_api.retrieval"):
        for _ in range(3):
            assert await searcher.vector_search(uuid4(), [0.0] * EMBEDDING_DIM, 5) == []
    assert [r.message for r in caplog.records if "not installed" in r.message] == [
        "pgvector is not installed; searching without iterative scan"
    ]
    assert searcher._iterative_scan is None  # not cached: the next search asks again


@pytest.fixture
async def seeded() -> AsyncIterator[tuple[async_sessionmaker[AsyncSession], UUID]]:
    with PostgresContainer("pgvector/pgvector:pg17", driver="asyncpg") as pg:
        url = pg.get_connection_url()
        config = Config(str(ALEMBIC_INI))
        config.set_main_option("sqlalchemy.url", url)
        await asyncio.to_thread(command.upgrade, config, "head")

        engine = create_async_engine(url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        embedder = FakeEmbedder(EMBEDDING_DIM)
        vectors = await embedder.embed(TEXTS)
        book = Book(id=uuid4(), title="T")
        async with sessions.begin() as session:
            session.add(book)
            await session.flush()
            session.add_all(
                Chunk(book_id=book.id, ordinal=i, text=t, page=i + 1, embedding=v)
                for i, (t, v) in enumerate(zip(TEXTS, vectors, strict=True))
            )
        yield sessions, book.id
        await engine.dispose()


async def test_text_search_matches_any_word(
    seeded: tuple[async_sessionmaker[AsyncSession], UUID],
) -> None:
    sessions, book_id = seeded
    found = await SqlChunkSearcher(sessions).text_search(book_id, "Hà Nội thủ đô?", 10)
    assert found[0].text == TEXTS[2]
    assert {c.text for c in found} == {TEXTS[0], TEXTS[2]}
    assert await SqlChunkSearcher(sessions).text_search(book_id, "?!", 10) == []


async def test_vector_search_finds_the_nearest_chunk(
    seeded: tuple[async_sessionmaker[AsyncSession], UUID],
) -> None:
    sessions, book_id = seeded
    [vector] = await FakeEmbedder(EMBEDDING_DIM).embed([TEXTS[1]])
    found = await SqlChunkSearcher(sessions).vector_search(book_id, vector, 2)
    assert found[0].text == TEXTS[1]
    assert found[0].page == 2


async def test_hybrid_retrieval_end_to_end(
    seeded: tuple[async_sessionmaker[AsyncSession], UUID],
) -> None:
    sessions, book_id = seeded
    retriever = HybridRetriever(
        SqlChunkSearcher(sessions), FakeEmbedder(EMBEDDING_DIM), FakeReranker()
    )
    result = await retriever.retrieve(book_id, "thủ đô Hà Nội", top_k=2)
    assert result[0].text == TEXTS[2]
    assert len(result) == 2


async def test_vector_search_returns_the_books_chunks_when_only_the_hnsw_index_applies() -> None:
    """With only the HNSW index usable, the `book_id` filter is applied after the index walk;
    without `hnsw.iterative_scan` the walk keeps ~40 candidates and almost none are this book's."""
    with PostgresContainer("pgvector/pgvector:pg17", driver="asyncpg") as pg:
        url = pg.get_connection_url()
        config = Config(str(ALEMBIC_INI))
        config.set_main_option("sqlalchemy.url", url)
        await asyncio.to_thread(command.upgrade, config, "head")

        embedder = FakeEmbedder(EMBEDDING_DIM)
        own_texts = [f"own passage {i} about rivers" for i in range(5)]
        other_texts = [f"other passage {i} about mountains" for i in range(400)]
        own_vectors = await embedder.embed(own_texts)
        other_vectors = await embedder.embed(other_texts)
        own_book, other_book = Book(id=uuid4(), title="own"), Book(id=uuid4(), title="other")

        engine = create_async_engine(url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions.begin() as session:
            session.add_all([own_book, other_book])
            await session.flush()
            session.add_all(
                Chunk(book_id=book.id, ordinal=i, text=t, embedding=v)
                for book, texts, vectors in (
                    (own_book, own_texts, own_vectors),
                    (other_book, other_texts, other_vectors),
                )
                for i, (t, v) in enumerate(zip(texts, vectors, strict=True))
            )
        async with engine.begin() as conn:
            # Leave the planner no exact path: no `book_id` indexes and no sequential scan.
            await conn.execute(text("DROP INDEX ix_chunks_book_id"))
            await conn.execute(text("ALTER TABLE chunks DROP CONSTRAINT uq_chunks_book_id_ordinal"))
        await engine.dispose()
        # New connections pick up the database-level setting.
        admin = create_async_engine(url, isolation_level="AUTOCOMMIT")
        async with admin.connect() as conn:
            await conn.execute(text(f"ALTER DATABASE {pg.dbname} SET enable_seqscan = off"))
        await admin.dispose()

        engine = create_async_engine(url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        [query] = await embedder.embed(["other passage about mountains"])
        found = await SqlChunkSearcher(sessions).vector_search(own_book.id, query, 30)
        await engine.dispose()
    assert {c.text for c in found} == set(own_texts)


async def test_qdrant_searcher_reads_vectors_from_qdrant_and_text_from_postgres(
    seeded: tuple[async_sessionmaker[AsyncSession], UUID],
) -> None:
    sessions, book_id = seeded
    embedder = FakeEmbedder(EMBEDDING_DIM)
    async with sessions() as session:
        rows = (await session.scalars(select(Chunk).where(Chunk.book_id == book_id))).all()
        items = [(c.id, c.embedding) for c in rows]
    index = QdrantVectorIndex(AsyncQdrantClient(location=":memory:"), "chunks")
    other_book = uuid4()
    await index.upsert(book_id, items)
    await index.upsert(other_book, [(uuid4(), items[0][1])])  # another book's point never appears
    assert await vector_counts(sessions, index, book_id) == (3, 3)

    searcher = QdrantChunkSearcher(index, sessions, SqlChunkSearcher(sessions))
    [vector] = await embedder.embed([TEXTS[1]])
    found = await searcher.vector_search(book_id, vector, 2)
    assert found[0].text == TEXTS[1]
    assert len(found) == 2
    assert found[0].page == 2
    assert (await searcher.text_search(book_id, "Hà Nội thủ đô?", 10))[0].text == TEXTS[2]

    await index.delete_book(book_id)
    assert await index.count(book_id) == 0
    assert await index.count(other_book) == 1
