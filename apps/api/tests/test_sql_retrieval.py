import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from book_rag.providers import FakeEmbedder, FakeReranker
from book_rag.retrieval import HybridRetriever
from book_rag_api.models import EMBEDDING_DIM, Book, Chunk
from book_rag_api.retrieval import SqlChunkSearcher, or_query

ALEMBIC_INI = Path(__file__).parents[1] / "alembic.ini"

TEXTS = [
    "Sông Hồng chảy qua Hà Nội",
    "Núi Fansipan cao nhất Đông Dương",
    "Hà Nội là thủ đô của Việt Nam",
]


def test_or_query_keeps_only_words() -> None:
    assert or_query("sông Hồng: 'Hà Nội' & !x") == "sông | Hồng | Hà | Nội | x"
    assert or_query("?! &") == ""


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
