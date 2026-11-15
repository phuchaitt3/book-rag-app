"""A tiny tracing hook for the retrieval code (#225).

This package names no tracing library, as with `RetrievalObserver`: the API passes a `Tracer`
that opens OpenTelemetry spans. `NoopTracer` is the default, so tracing costs nothing when off.
"""

from contextlib import AbstractContextManager, nullcontext
from typing import Protocol


class SpanHandle(Protocol):
    """What the code inside a span may do: add an attribute."""

    def set_attribute(self, key: str, value: str | int | float | bool) -> None: ...


class Tracer(Protocol):
    def span(
        self, name: str, **attributes: str | int | float | bool
    ) -> AbstractContextManager[SpanHandle]:
        """A context manager that times the block as one span named `name`."""
        ...


class _NoopSpan:
    def set_attribute(self, key: str, value: str | int | float | bool) -> None:
        return None


class NoopTracer:
    def span(
        self, name: str, **attributes: str | int | float | bool
    ) -> AbstractContextManager[SpanHandle]:
        return nullcontext(_NoopSpan())
