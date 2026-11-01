from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

from book_rag_api.config import Settings
from book_rag_api.main import ReadyStatus, create_app, get_engine

# Nothing listens on port 1, so connecting fails fast.
UNREACHABLE_DB = "postgresql+asyncpg://x:x@127.0.0.1:1/x"


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app(Settings(database_url=UNREACHABLE_DB))
    engine = create_async_engine(UNREACHABLE_DB)
    app.dependency_overrides[get_engine] = lambda: engine
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


async def test_healthz_is_ok_without_database(client: AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readyz_reports_database_down(client: AsyncClient) -> None:
    response = await client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "down"}
    assert ReadyStatus.model_validate(response.json())  # the reply matches the documented model


async def test_readyz_ok_matches_the_documented_model(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def up(engine: object) -> None:
        return None

    monkeypatch.setattr("book_rag_api.main.ping", up)
    response = await client.get("/readyz")
    assert response.status_code == 200
    assert ReadyStatus.model_validate(response.json()).database == "up"
