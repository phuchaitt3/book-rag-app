"""Prometheus metrics served at `/metrics` (ADR 0010).

One `Metrics` object per app holds its own registry, so tests that build several apps do not
clash on global metric names. Every label takes values from a small fixed set (route templates,
stage names, fallback reasons), so the number of series does not grow with traffic.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest
from prometheus_client.core import GaugeMetricFamily, Metric
from prometheus_client.exposition import CONTENT_TYPE_LATEST
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from book_rag_api.models import JOB_STATUSES, IngestionJob

# Fixed in code so histograms from several instances can be added together.
REQUEST_BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120)
STAGE_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30)
# First token: the benchmark's p90 is 11.9 s with the reranker; 20 s is the SLO edge (slo.md).
FIRST_TOKEN_BUCKETS = (0.5, 1, 2.5, 5, 10, 15, 20, 30, 60, 120)
JOBS_SCRAPE_TIMEOUT = 2.0  # seconds; a slow database must not stall the scrape
UNMATCHED = "unmatched"
METRICS_PATH = "/metrics"


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class JobRow:
    """The ingestion jobs in one status: how many, and the oldest timestamps among them."""

    status: str
    count: int
    oldest_created: datetime | None
    oldest_started: datetime | None


JobReader = Callable[[], Awaitable[list[JobRow]]]


async def read_job_rows(engine: AsyncEngine) -> list[JobRow]:
    """One grouped query over all owners' jobs; `ingestion_jobs.status` is small and indexed
    by the table's own size, so this stays cheap at scrape frequency."""
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(
                IngestionJob.status,
                func.count(),
                func.min(IngestionJob.created_at),
                func.min(IngestionJob.started_at),
            ).group_by(IngestionJob.status)
        )
        return [JobRow(s, n, created, started) for s, n, created, started in result.all()]


class JobsCollector:
    """Job gauges, filled at scrape time by `Metrics.refresh_jobs`. With no snapshot (the
    last read failed) it exports nothing, so a stale value never hides a dead database."""

    def __init__(self) -> None:
        self.snapshot: list[JobRow] | None = None

    def collect(self) -> Iterable[Metric]:
        rows = self.snapshot
        if rows is None:
            return
        now = datetime.now(UTC)
        by_status = {r.status: r for r in rows}
        jobs = GaugeMetricFamily(
            "ingestion_jobs", "Ingestion jobs by status, all owners.", labels=["status"]
        )
        for status in JOB_STATUSES:
            jobs.add_metric([status], by_status[status].count if status in by_status else 0)
        yield jobs
        yield GaugeMetricFamily(
            "ingestion_oldest_queued_age_seconds",
            "Age of the oldest queued job; 0 when none is queued.",
            value=_age(now, by_status.get("queued"), "oldest_created"),
        )
        yield GaugeMetricFamily(
            "ingestion_oldest_running_age_seconds",
            "Time the longest-running job has been running; 0 when none is running.",
            value=_age(now, by_status.get("running"), "oldest_started"),
        )


def _age(now: datetime, row: JobRow | None, field: str) -> float:
    since: datetime | None = getattr(row, field, None)
    return max(0.0, (now - since).total_seconds()) if since is not None else 0.0


class Metrics:
    """Also the `RetrievalObserver` the retriever reports to."""

    content_type = CONTENT_TYPE_LATEST

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.request_seconds = Histogram(
            "http_request_duration_seconds",
            "Time from request start to the last response byte (the whole answer, for a stream).",
            ["method", "route", "status"],
            buckets=REQUEST_BUCKETS,
            registry=self.registry,
        )
        self.retrieval_seconds = Histogram(
            "retrieval_duration_seconds",
            "Time to retrieve the passages for one question.",
            buckets=STAGE_BUCKETS,
            registry=self.registry,
        )
        self.stage_seconds = Histogram(
            "retrieval_stage_duration_seconds",
            "Time of one retrieval step: embed, search or rerank.",
            ["stage"],
            buckets=STAGE_BUCKETS,
            registry=self.registry,
        )
        self.rerank_fallbacks = Counter(
            "rerank_fallbacks",
            "Questions answered in the fused order because the reranker failed.",
            ["reason"],
            registry=self.registry,
        )
        self.first_token_seconds = Histogram(
            "chat_first_token_duration_seconds",
            "Time from the chat request's start to the first streamed token event of a model "
            "answer (abstained replies are not counted).",
            buckets=FIRST_TOKEN_BUCKETS,
            registry=self.registry,
        )
        self.jobs = JobsCollector()
        self.registry.register(self.jobs)
        self.abstentions = Counter(
            "chat_abstentions",
            "Questions answered with the fixed not-found reply, without calling the model.",
            ["reason"],  # no_passages | low_score
            registry=self.registry,
        )

    def abstained(self, reason: str) -> None:
        self.abstentions.labels(reason).inc()

    def stage_done(self, stage: str, seconds: float) -> None:
        self.stage_seconds.labels(stage).observe(seconds)

    def retrieval_done(self, seconds: float) -> None:
        self.retrieval_seconds.observe(seconds)

    def rerank_fallback(self, reason: str) -> None:
        self.rerank_fallbacks.labels(reason).inc()

    def first_token(self, seconds: float) -> None:
        self.first_token_seconds.observe(seconds)

    async def refresh_jobs(self, read: JobReader) -> None:
        """Read the job table for this scrape. A failure (database down, slow) drops the job
        gauges for this scrape and never breaks `/metrics`."""
        try:
            async with asyncio.timeout(JOBS_SCRAPE_TIMEOUT):
                self.jobs.snapshot = await read()
        except Exception:
            self.jobs.snapshot = None
            log.warning("could not read ingestion jobs for /metrics", exc_info=True)

    def render(self) -> bytes:
        return generate_latest(self.registry)


class MetricsMiddleware:
    """Times each HTTP request. Pure ASGI, so a streamed body is timed to its last byte."""

    def __init__(self, app: ASGIApp, metrics: Metrics) -> None:
        self.app = app
        self.metrics = metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] == METRICS_PATH:
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = 500  # what a request that raises before answering ends up as

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            # The router puts the matched route in the scope; the template, not the raw path,
            # keeps the label set small.
            route: Any = scope.get("route")
            self.metrics.request_seconds.labels(
                scope["method"], getattr(route, "path", UNMATCHED), str(status)
            ).observe(time.perf_counter() - started)
