"""Prometheus metrics served at `/metrics` (ADR 0010).

One `Metrics` object per app holds its own registry, so tests that build several apps do not
clash on global metric names. Every label takes values from a small fixed set (route templates,
stage names, fallback reasons), so the number of series does not grow with traffic.
"""

import time
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest
from prometheus_client.exposition import CONTENT_TYPE_LATEST
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Fixed in code so histograms from several instances can be added together.
REQUEST_BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120)
STAGE_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30)
UNMATCHED = "unmatched"
METRICS_PATH = "/metrics"


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

    def stage_done(self, stage: str, seconds: float) -> None:
        self.stage_seconds.labels(stage).observe(seconds)

    def retrieval_done(self, seconds: float) -> None:
        self.retrieval_seconds.observe(seconds)

    def rerank_fallback(self, reason: str) -> None:
        self.rerank_fallbacks.labels(reason).inc()

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
