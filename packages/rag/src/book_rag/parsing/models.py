"""What the PDF parser hands to the chunker."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PageText:
    """Text of one section that sits on one page (1-based page number)."""

    page: int
    text: str


@dataclass(frozen=True, slots=True)
class Section:
    title: str
    path: str  # breadcrumb of titles, e.g. "Chương 1 > 1.2 Nguồn gốc"
    level: int
    segments: tuple[PageText, ...]


@dataclass(frozen=True, slots=True)
class ParsedBook:
    title: str
    page_count: int
    sections: tuple[Section, ...]
