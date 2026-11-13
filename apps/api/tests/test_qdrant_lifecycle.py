import httpx
import procrastinate
import pytest
from procrastinate import testing
from qdrant_client.http.exceptions import UnexpectedResponse

import book_rag_api.main as main
from book_rag_api.config import Settings
from book_rag_api.qdrant_index import QdrantVectorIndex


def unexpected(status_code: int) -> UnexpectedResponse:
    return UnexpectedResponse(status_code, "reason", b"", httpx.Headers())


class FakeQdrantClient:
    """Records the calls the index makes; `create_error` is raised by create_collection."""

    def __init__(self, create_error: Exception | None = None) -> None:
        self.create_error = create_error
        self.created = 0
        self.indexed = 0
        self.closed = 0

    async def collection_exists(self, name: str) -> bool:
        return False

    async def create_collection(self, name: str, **kwargs: object) -> None:
        self.created += 1
        if self.create_error is not None:
            raise self.create_error

    async def create_payload_index(self, name: str, *args: object, **kwargs: object) -> None:
        self.indexed += 1

    async def close(self) -> None:
        self.closed += 1


def make_index(client: FakeQdrantClient) -> QdrantVectorIndex:
    return QdrantVectorIndex(client, "chunks")  # type: ignore[arg-type]


async def test_already_exists_is_success_when_the_other_process_won_the_race() -> None:
    client = FakeQdrantClient(create_error=unexpected(409))
    index = make_index(client)
    await index._ensure_collection()
    assert client.created == 1
    assert client.indexed == 1  # setup carried on past the conflict


async def test_other_errors_still_raise() -> None:
    client = FakeQdrantClient(create_error=unexpected(500))
    index = make_index(client)
    with pytest.raises(UnexpectedResponse):
        await index._ensure_collection()
    assert client.indexed == 0


async def test_close_closes_the_client() -> None:
    client = FakeQdrantClient()
    await make_index(client).close()
    assert client.closed == 1


async def test_api_lifespan_closes_the_qdrant_client(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeQdrantClient()
    monkeypatch.setattr(main, "AsyncQdrantClient", lambda **kwargs: client)
    app = main.create_app(
        Settings(vector_store="qdrant"),
        queue=procrastinate.App(connector=testing.InMemoryConnector()),
        storage=object(),  # type: ignore[arg-type]
        llm=object(),  # type: ignore[arg-type]
        embedder=object(),  # type: ignore[arg-type]
    )
    async with app.router.lifespan_context(app):
        assert client.closed == 0
    assert client.closed == 1
