import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from book_rag.providers import FakeEmbedder, FakeReranker
from book_rag.retrieval import HybridRetriever
from book_rag_api.auth import DEV_OWNER
from book_rag_api.lexical import refresh_book_stats
from book_rag_api.models import EMBEDDING_DIM, Book, BookTerm, Chunk
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
            assert (
                await searcher.vector_search(
                    [uuid4()], [0.0] * EMBEDDING_DIM, 5, owner_id=DEV_OWNER
                )
                == []
            )
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
        book = Book(id=uuid4(), title="T", owner_id=DEV_OWNER)
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
    found = await SqlChunkSearcher(sessions).text_search(
        [book_id], "Hà Nội thủ đô?", 10, owner_id=DEV_OWNER
    )
    assert found[0].text == TEXTS[2]
    assert {c.text for c in found} == {TEXTS[0], TEXTS[2]}
    assert (
        await SqlChunkSearcher(sessions).text_search([book_id], "?!", 10, owner_id=DEV_OWNER) == []
    )


async def test_vector_search_finds_the_nearest_chunk(
    seeded: tuple[async_sessionmaker[AsyncSession], UUID],
) -> None:
    sessions, book_id = seeded
    [vector] = await FakeEmbedder(EMBEDDING_DIM).embed([TEXTS[1]])
    found = await SqlChunkSearcher(sessions).vector_search([book_id], vector, 2, owner_id=DEV_OWNER)
    assert found[0].text == TEXTS[1]
    assert found[0].page == 2


async def test_hybrid_retrieval_end_to_end(
    seeded: tuple[async_sessionmaker[AsyncSession], UUID],
) -> None:
    sessions, book_id = seeded
    retriever = HybridRetriever(
        SqlChunkSearcher(sessions), FakeEmbedder(EMBEDDING_DIM), FakeReranker()
    )
    result = await retriever.retrieve([book_id], "thủ đô Hà Nội", owner_id=DEV_OWNER, top_k=2)
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
        own_book, other_book = (
            Book(id=uuid4(), title="own", owner_id=DEV_OWNER),
            Book(id=uuid4(), title="other", owner_id=DEV_OWNER),
        )

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
        found = await SqlChunkSearcher(sessions).vector_search(
            [own_book.id], query, 30, owner_id=DEV_OWNER
        )
        await engine.dispose()
    assert {c.text for c in found} == set(own_texts)


async def test_search_over_several_books_returns_only_the_chosen_ones() -> None:
    """Three books hold the same passages; a search over two of them never returns the third's."""
    with PostgresContainer("pgvector/pgvector:pg17", driver="asyncpg") as pg:
        url = pg.get_connection_url()
        config = Config(str(ALEMBIC_INI))
        config.set_main_option("sqlalchemy.url", url)
        await asyncio.to_thread(command.upgrade, config, "head")

        engine = create_async_engine(url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        embedder = FakeEmbedder(EMBEDDING_DIM)
        vectors = await embedder.embed(TEXTS)
        books = [Book(id=uuid4(), title=f"T{i}", owner_id=DEV_OWNER) for i in range(3)]
        async with sessions.begin() as session:
            session.add_all(books)
            await session.flush()
            session.add_all(
                Chunk(book_id=book.id, ordinal=i, text=t, page=i + 1, embedding=v)
                for book in books
                for i, (t, v) in enumerate(zip(TEXTS, vectors, strict=True))
            )
            await session.flush()
            for book in books:
                await refresh_book_stats(session, book.id)
        chosen = [books[0].id, books[2].id]
        searcher = SqlChunkSearcher(sessions)

        by_vector = await searcher.vector_search(chosen, vectors[2], 30, owner_id=DEV_OWNER)
        by_text = await searcher.text_search(chosen, "Hà Nội thủ đô?", 30, owner_id=DEV_OWNER)
        one = await searcher.vector_search([books[1].id], vectors[2], 30, owner_id=DEV_OWNER)
        retriever = HybridRetriever(searcher, embedder, FakeReranker())
        hybrid = await retriever.retrieve(chosen, "thủ đô Hà Nội", owner_id=DEV_OWNER, top_k=10)
        await engine.dispose()

    assert len(by_vector) == 2 * len(TEXTS)  # every chunk of both chosen books
    assert {c.book_id for c in by_vector} == set(chosen)
    assert by_text
    assert {c.book_id for c in by_text} == set(chosen)
    assert {c.book_id for c in one} == {books[1].id}
    assert hybrid
    assert {c.book_id for c in hybrid} == set(chosen)


BM25_TEXTS = [
    # Common words repeated, no rare word: ts_rank_cd's favourite.
    "của của của là là là và và và có có có",
    "Vua Gia Long lập ra triều Nguyễn và là vua đầu tiên",
    "Thành phố Huế là kinh đô của triều Nguyễn",
    "Sông Hương chảy qua Huế",
    "Lễ hội Huế diễn ra của mỗi năm và là dịp lớn",
]


@pytest.fixture
async def bm25_book() -> AsyncIterator[tuple[async_sessionmaker[AsyncSession], UUID]]:
    with PostgresContainer("pgvector/pgvector:pg17", driver="asyncpg") as pg:
        url = pg.get_connection_url()
        config = Config(str(ALEMBIC_INI))
        config.set_main_option("sqlalchemy.url", url)
        await asyncio.to_thread(command.upgrade, config, "head")
        engine = create_async_engine(url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        book = Book(id=uuid4(), title="B", owner_id=DEV_OWNER)
        async with sessions.begin() as session:
            session.add(book)
            await session.flush()
            session.add_all(
                Chunk(book_id=book.id, ordinal=i, text=t, page=i + 1)
                for i, t in enumerate(BM25_TEXTS)
            )
            await session.flush()
            await refresh_book_stats(session, book.id)
        yield sessions, book.id
        await engine.dispose()


async def test_refresh_book_stats_counts_tokens_and_document_frequency(
    bm25_book: tuple[async_sessionmaker[AsyncSession], UUID],
) -> None:
    sessions, book_id = bm25_book
    async with sessions() as session:
        lengths = (
            await session.execute(
                select(Chunk.ordinal, Chunk.token_count)
                .where(Chunk.book_id == book_id)
                .order_by(Chunk.ordinal)
            )
        ).all()
        df = {
            t.term: t.df
            for t in (
                await session.execute(select(BookTerm).where(BookTerm.book_id == book_id))
            ).scalars()
        }
    # 12 words and 11 adjacent pairs (#95).
    assert lengths[0].token_count == 23
    assert df["huế"] == 3
    assert df["của"] == 3
    assert df["sông"] == 1
    assert df["thành phố"] == 1  # a syllable pair is a term
    assert df["huế là"] == 1
    # A second refresh replaces, never doubles.
    async with sessions.begin() as session:
        await refresh_book_stats(session, book_id)
        again = await session.scalar(select(BookTerm.df).where(BookTerm.term == "huế"))
    assert again == 3


async def test_bm25_ranks_the_rare_word_above_repeated_common_words(
    bm25_book: tuple[async_sessionmaker[AsyncSession], UUID],
) -> None:
    sessions, book_id = bm25_book
    searcher = SqlChunkSearcher(sessions)
    found = await searcher.text_search(
        [book_id], "Ai là vua đầu tiên của triều Nguyễn?", 5, owner_id=DEV_OWNER
    )
    assert found[0].text == BM25_TEXTS[1]
    assert BM25_TEXTS[0] not in [c.text for c in found[:2]]
    assert found[0].page == 2


async def test_bm25_with_only_common_words_still_returns_chunks(
    bm25_book: tuple[async_sessionmaker[AsyncSession], UUID],
) -> None:
    sessions, book_id = bm25_book
    found = await SqlChunkSearcher(sessions).text_search([book_id], "của là", 5, owner_id=DEV_OWNER)
    assert found  # no word is rare: every query word selects candidates


async def test_bm25_ignores_words_the_book_lacks_and_punctuation(
    bm25_book: tuple[async_sessionmaker[AsyncSession], UUID],
) -> None:
    sessions, book_id = bm25_book
    searcher = SqlChunkSearcher(sessions)
    assert await searcher.text_search([book_id], "zzzzqq", 5, owner_id=DEV_OWNER) == []
    assert await searcher.text_search([book_id], "?!", 5, owner_id=DEV_OWNER) == []
    found = await searcher.text_search(
        [book_id], "Huế') | !x & 'a\b http://a.b/c:d", 5, owner_id=DEV_OWNER
    )
    assert {c.text for c in found} == {BM25_TEXTS[2], BM25_TEXTS[3], BM25_TEXTS[4]}


async def test_a_book_without_statistics_falls_back_to_ts_rank(
    seeded: tuple[async_sessionmaker[AsyncSession], UUID],
) -> None:
    sessions, book_id = seeded  # its chunks were inserted without refresh_book_stats
    found = await SqlChunkSearcher(sessions).text_search(
        [book_id], "Hà Nội thủ đô?", 10, owner_id=DEV_OWNER
    )
    assert found[0].text == TEXTS[2]


async def test_bigram_tsvector_pairs_adjacent_words_with_positions(
    bm25_book: tuple[async_sessionmaker[AsyncSession], UUID],
) -> None:
    sessions, _ = bm25_book
    async with sessions() as session:
        got = await session.scalar(text("SELECT bigram_tsvector('Học sinh học, học sinh')::text"))
        empty = await session.scalar(text("SELECT bigram_tsvector('một')::text"))
    assert got == "'học học':3 'học sinh':1,4 'sinh học':2"
    assert empty == ""


async def test_bm25_finds_the_adjacent_pair_before_the_scattered_words(
    bm25_book: tuple[async_sessionmaker[AsyncSession], UUID],
) -> None:
    sessions, book_id = bm25_book
    async with sessions.begin() as session:
        session.add_all(
            [
                Chunk(book_id=book_id, ordinal=10, text="Gia đình nhà Nguyễn ở Long An"),
                Chunk(book_id=book_id, ordinal=11, text="Vua Gia Long lập ra triều"),
            ]
        )
        await session.flush()
        await refresh_book_stats(session, book_id)
    found = await SqlChunkSearcher(sessions).text_search(
        [book_id], "Gia Long", 5, owner_id=DEV_OWNER
    )
    texts = [c.text for c in found]
    scattered = "Gia đình nhà Nguyễn ở Long An"
    assert {"Vua Gia Long lập ra triều", BM25_TEXTS[1]} == set(texts[:2])
    assert texts[2] == scattered
