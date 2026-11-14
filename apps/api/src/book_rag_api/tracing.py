"""OpenTelemetry tracing, off by default (#225).

Setting `OTEL_EXPORTER_OTLP_ENDPOINT` turns it on: spans go to that OTLP/HTTP collector (Jaeger
in `compose.observability.yaml`). With it unset, `build_tracing` returns None, no provider or
exporter is created, the SDK is not imported, and the manual spans are `NoopTracer` calls.

The provider is passed around, never installed as the process-wide one, so tests can build their
own and a second `create_app` never hits OpenTelemetry's "set once" rule.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from opentelemetry import trace
from opentelemetry.trace import Span, Tracer

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SpanExporter

TRACER_NAME = "book_rag"


def build_tracing(
    endpoint: str | None,
    *,
    service_name: str = "book-rag-api",
    exporter: "SpanExporter | None" = None,
) -> "TracerProvider | None":
    """The tracer provider, or None when tracing is off.

    Tracing is on when `endpoint` (`OTEL_EXPORTER_OTLP_ENDPOINT`) is set. `exporter` (tests) is
    used instead of the OTLP one, with a synchronous processor so a test reads spans at once.
    """
    if not endpoint and exporter is None:
        return None
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    if exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    else:
        provider.add_span_processor(BatchSpanProcessor(_otlp_exporter(str(endpoint))))
    return provider


def _otlp_exporter(endpoint: str) -> "SpanExporter":
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    return OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces")


def instrument_app(app: Any, provider: "TracerProvider") -> None:
    """Spans for each HTTP request. Call after the app's other middleware is added."""
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)


def instrument_engine(engine: Any, provider: "TracerProvider") -> None:
    """Spans for each SQL statement of an `AsyncEngine`.

    This attaches the instrumentation's own `EngineTracer` to the one engine instead of calling
    `SQLAlchemyInstrumentor().instrument()`. That entry point refuses to run on SQLAlchemy 2.1
    (it checks `< 2.1.0`; the lock holds 2.1.x), patches `create_engine` for the whole process,
    and can be switched on only once, which does not suit an app built many times in tests.
    """
    from opentelemetry import metrics
    from opentelemetry.instrumentation.sqlalchemy.engine import EngineTracer

    usage = metrics.get_meter(TRACER_NAME).create_up_down_counter("db.client.connections.usage")
    EngineTracer(provider.get_tracer(TRACER_NAME), engine.sync_engine, usage)  # type: ignore[no-untyped-call]


class OtelTracer:
    """The `book_rag.tracing.Tracer` that opens OpenTelemetry spans from one provider."""

    def __init__(self, tracer: Tracer) -> None:
        self._tracer = tracer

    @classmethod
    def from_provider(cls, provider: "TracerProvider") -> "OtelTracer":
        return cls(provider.get_tracer(TRACER_NAME))

    @contextmanager
    def span(self, name: str, **attributes: str | int | float | bool) -> Iterator[Span]:
        with self._tracer.start_as_current_span(name, attributes=attributes) as span:
            yield span


def current_trace_id() -> str | None:
    """The active span's trace ID as 32 hex digits (the ID Jaeger shows), or None."""
    context = trace.get_current_span().get_span_context()
    return f"{context.trace_id:032x}" if context.is_valid else None
