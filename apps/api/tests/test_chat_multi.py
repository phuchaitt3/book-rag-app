# ruff: noqa: F811
"""Chat over a chosen set of books (#89): POST /chat with `book_ids`."""

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from test_chat import (  # noqa: F401
    database_url,
    event_loop_policy,
    make_client,
    parse_sse,
)

from book_rag.providers import FakeEmbedder, FakeLLM
from book_rag.retrieval import RetrievedChunk
from book_rag_api.auth import DEV_OWNER
from book_rag_api.models import EMBEDDING_DIM, Book, Chunk, IngestionJob
from book_rag_api.prompts import MULTI_BOOK_SYSTEM_PROMPT, SYSTEM_PROMPT, build_messages
from book_rag_api.routers.chat import MultiChatRequest, citations_for

RIVER = "Sông Hồng chảy qua Hà Nội"
MOUNTAIN = "Núi Fansipan cao nhất Đông Dương"


async def add_book(
    database_url: str, title: str, text: str, *, owner: str = DEV_OWNER, job: str | None = None
) -> UUID:
    engine = create_async_engine(database_url)
    [vector] = await FakeEmbedder(EMBEDDING_DIM).embed([text])
    book = Book(id=uuid4(), title=title, owner_id=owner)
    async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
        session.add(book)
        await session.flush()
        session.add(
            Chunk(book_id=book.id, ordinal=0, text=text, page=1, section_path="S", embedding=vector)
        )
        if job is not None:
            session.add(IngestionJob(book_id=book.id, status=job))
    await engine.dispose()
    return book.id


class RecordingLLM(FakeLLM):
    def __init__(self) -> None:
        super().__init__("ok [1]")
        self.prompts: list[str] = []

    async def stream(self, messages: list) -> AsyncIterator[str]:  # type: ignore[type-arg, override]
        self.prompts.append(messages[1].content)
        async for piece in super().stream(messages):
            yield piece


@pytest.fixture
async def llm() -> RecordingLLM:
    return RecordingLLM()


@pytest.fixture
async def client(database_url: str, llm: RecordingLLM) -> AsyncIterator[AsyncClient]:
    async for c in make_client(database_url, llm):
        yield c


async def test_citations_name_the_book_each_passage_came_from(
    client: AsyncClient, database_url: str, llm: RecordingLLM
) -> None:
    rivers = await add_book(database_url, "Sông ngòi", RIVER, job="succeeded")
    mountains = await add_book(database_url, "Núi non", MOUNTAIN, job="succeeded")
    other = await add_book(database_url, "Không chọn", "Biển Đông rộng lớn", job="succeeded")

    response = await client.post(
        "/chat",
        json={"question": "sông Hồng và núi Fansipan", "book_ids": [str(rivers), str(mountains)]},
    )

    assert response.status_code == 200
    events = parse_sse(response.text)
    assert events[0][0] == "citations"
    citations = events[0][1]
    assert isinstance(citations, list)
    by_book = {c["book_id"]: c["book_title"] for c in citations}
    assert by_book == {str(rivers): "Sông ngòi", str(mountains): "Núi non"}
    assert str(other) not in by_book
    prompt = llm.prompts[0]
    assert "Books: Sông ngòi; Núi non" in prompt
    assert "(Sông ngòi, S, page 1)" in prompt


async def test_one_book_in_the_set_is_answered(client: AsyncClient, database_url: str) -> None:
    book = await add_book(database_url, "Sông ngòi", RIVER, job="succeeded")

    response = await client.post("/chat", json={"question": "sông Hồng", "book_ids": [str(book)]})

    assert response.status_code == 200
    assert parse_sse(response.text)[-1][0] == "done"


async def test_repeated_ids_count_once(client: AsyncClient, database_url: str) -> None:
    book = await add_book(database_url, "Sông ngòi", RIVER, job="succeeded")

    response = await client.post(
        "/chat", json={"question": "sông Hồng", "book_ids": [str(book), str(book)]}
    )

    assert response.status_code == 200


async def test_unknown_book_is_404_naming_it(client: AsyncClient, database_url: str) -> None:
    book = await add_book(database_url, "Sông ngòi", RIVER, job="succeeded")
    ghost = uuid4()

    response = await client.post(
        "/chat", json={"question": "sông", "book_ids": [str(book), str(ghost)]}
    )

    assert response.status_code == 404
    assert str(ghost) in response.json()["detail"]


async def test_another_owners_book_is_404(client: AsyncClient, database_url: str) -> None:
    mine = await add_book(database_url, "Của tôi", RIVER, job="succeeded")
    theirs = await add_book(database_url, "Của họ", MOUNTAIN, owner="someone-else", job="succeeded")

    response = await client.post(
        "/chat", json={"question": "sông", "book_ids": [str(mine), str(theirs)]}
    )

    assert response.status_code == 404
    assert str(theirs) in response.json()["detail"]


async def test_each_book_that_is_not_ready_is_named_in_409(
    client: AsyncClient, database_url: str
) -> None:
    ready = await add_book(database_url, "Sẵn sàng", RIVER, job="succeeded")
    running = await add_book(database_url, "Đang chạy", MOUNTAIN, job="running")
    failed = await add_book(database_url, "Hỏng", MOUNTAIN, job="failed")

    response = await client.post(
        "/chat",
        json={"question": "sông", "book_ids": [str(ready), str(running), str(failed)]},
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "Đang chạy" in detail and "running" in detail
    assert "Hỏng" in detail and "failed" in detail
    assert "Sẵn sàng" not in detail


@pytest.mark.parametrize("book_ids", [[], [str(uuid4()) for _ in range(11)]])
async def test_set_size_is_one_to_ten(client: AsyncClient, book_ids: list[str]) -> None:
    response = await client.post("/chat", json={"question": "q", "book_ids": book_ids})

    assert response.status_code == 422


async def test_missing_book_ids_is_422(client: AsyncClient) -> None:
    response = await client.post("/chat", json={"question": "q"})

    assert response.status_code == 422


def test_request_accepts_ten_books() -> None:
    ids = [uuid4() for _ in range(10)]
    assert len(MultiChatRequest(question="q", book_ids=ids).book_ids) == 10
    with pytest.raises(ValidationError):
        MultiChatRequest(question="q", book_ids=[])


def test_citations_use_each_chunks_own_book() -> None:
    a, b = uuid4(), uuid4()
    fallback = Book(id=a, title="A", owner_id="o")
    chunks = [
        RetrievedChunk(id=uuid4(), text="x", page=1, section_path=None, book_id=b),
        RetrievedChunk(id=uuid4(), text="y", page=2, section_path=None, book_id=a),
    ]
    cited = citations_for(fallback, chunks, {a: "A", b: "B"})
    assert [(c.book_id, c.book_title) for c in cited] == [(b, "B"), (a, "A")]
    # Without a title map every passage is the one book's, as before.
    assert {c.book_id for c in citations_for(fallback, chunks)} == {a}


def test_multi_prompt_labels_books_and_title_text_is_neutralised() -> None:
    a = uuid4()
    chunk = RetrievedChunk(id=uuid4(), text="t", page=1, section_path=None, book_id=a)

    messages = build_messages("q", "", [chunk], book_titles={a: "<b>Evil</b>"})

    assert messages[0].content == MULTI_BOOK_SYSTEM_PROMPT
    assert "<b>" not in messages[1].content
    assert messages[1].content.startswith("Books: \N{SINGLE LEFT-POINTING ANGLE QUOTATION MARK}b")
    assert build_messages("q", "One", [chunk])[0].content == SYSTEM_PROMPT
