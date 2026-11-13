import re
from collections.abc import AsyncIterator, Sequence
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from book_rag.providers import FakeEmbedder
from book_rag.retrieval import HybridRetriever, RetrievedChunk
from book_rag_api.config import Settings
from book_rag_api.main import create_app
from book_rag_api.metrics import Metrics

UNREACHABLE_DB = "postgresql+asyncpg://x:x@127.0.0.1:1/x"


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app(Settings(database_url=UNREACHABLE_DB))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def sample(text: str, line_start: str) -> float:
    match = re.search(rf"^{re.escape(line_start)} (\S+)$", text, re.MULTILINE)
    assert match, f"no sample {line_start!r} in:\n{text}"
    return float(match.group(1))


async def test_metrics_serves_the_prometheus_text_format(client: AsyncClient) -> None:
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "# TYPE http_request_duration_seconds histogram" in response.text
    assert "# TYPE rerank_fallbacks_total counter" in response.text


async def test_a_request_is_counted_under_its_route_template(client: AsyncClient) -> None:
    await client.get("/healthz")
    text = (await client.get("/metrics")).text
    key = 'http_request_duration_seconds_count{method="GET",route="/healthz",status="200"}'
    assert sample(text, key) == 1.0


async def test_unknown_paths_share_one_label(client: AsyncClient) -> None:
    for name in ("a", "b", "c"):
        assert (await client.get(f"/no-such-{name}")).status_code == 404
    text = (await client.get("/metrics")).text
    key = 'http_request_duration_seconds_count{method="GET",route="unmatched",status="404"}'
    assert sample(text, key) == 3.0


async def test_the_metrics_endpoint_does_not_time_itself(client: AsyncClient) -> None:
    await client.get("/metrics")
    assert 'route="/metrics"' not in (await client.get("/metrics")).text


async def test_the_endpoint_is_not_in_the_openapi_document(client: AsyncClient) -> None:
    assert "/metrics" not in (await client.get("/openapi.json")).json()["paths"]


async def test_two_apps_do_not_share_counters() -> None:
    first = create_app(Settings(database_url=UNREACHABLE_DB))
    second = create_app(Settings(database_url=UNREACHABLE_DB))
    async with AsyncClient(transport=ASGITransport(app=first), base_url="http://t") as c:
        await c.get("/healthz")
    async with AsyncClient(transport=ASGITransport(app=second), base_url="http://t") as c:
        assert "/healthz" not in (await c.get("/metrics")).text


class OneChunkSearcher:
    async def vector_search(
        self, book_id: UUID, embedding: Sequence[float], limit: int
    ) -> list[RetrievedChunk]:
        return [RetrievedChunk(id=uuid4(), text="x", page=1, section_path=None)]

    async def text_search(self, book_id: UUID, query: str, limit: int) -> list[RetrievedChunk]:
        return []


class DownReranker:
    async def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        raise TimeoutError


async def test_retrieval_reports_stages_and_a_fallback_into_the_registry() -> None:
    metrics = Metrics()
    retriever = HybridRetriever(
        OneChunkSearcher(), FakeEmbedder(), DownReranker(), observer=metrics
    )
    await retriever.retrieve(uuid4(), "q")
    text = metrics.render().decode()
    assert sample(text, 'rerank_fallbacks_total{reason="timeout"}') == 1.0
    assert sample(text, "retrieval_duration_seconds_count") == 1.0
    for stage in ("embed", "search", "rerank"):
        assert sample(text, f'retrieval_stage_duration_seconds_count{{stage="{stage}"}}') == 1.0
