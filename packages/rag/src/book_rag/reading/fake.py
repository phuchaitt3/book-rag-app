"""A deterministic reader for tests: no binary, no model."""

from __future__ import annotations

from collections.abc import Callable

from book_rag.reading.base import PageReadError


class FakePageReader:
    """Returns `text(call_number)` for the n-th call (1-based); records the call count."""

    name = "fake"

    def __init__(
        self, text: Callable[[int], str] | None = None, version: str = "1", fail_on: int = 0
    ) -> None:
        self.version = version
        self.calls = 0
        self._text = text or (lambda n: f"Trang quét số {n} có chữ ệ ữ ơ.")
        self._fail_on = fail_on  # raise on this call number (0 = never)

    def read(self, image: bytes) -> str:
        self.calls += 1
        if self.calls == self._fail_on:
            raise PageReadError("fake reader failure")
        return self._text(self.calls)
