"""Text PDF parsing with PyMuPDF. Sections come from the PDF outline (bookmarks).

A PDF without an outline becomes one section. Scanned PDFs have no text layer and are out of
scope here (OCR is a later experiment): they raise `NoTextError`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pymupdf

from book_rag.parsing.models import PageText, ParsedBook, Section

FRONT_MATTER = "(front matter)"


class NoTextError(ValueError):
    """The PDF has no extractable text, so it is probably a scan."""


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _heading_offset(page_text: str, title: str, after: int) -> int:
    """Where the heading `title` starts in `page_text` (at or after `after`), else `after`."""
    needle = _norm(title)
    if not needle:
        return after
    index = page_text.find(needle, after)
    return index if index >= 0 else after


def parse_pdf(source: Path | bytes, title: str | None = None) -> ParsedBook:
    """Parse a text PDF into sections of page-tagged text."""
    if isinstance(source, bytes):
        doc = pymupdf.open(stream=source, filetype="pdf")
    else:
        doc = pymupdf.open(source)
    with doc:
        pages = [_norm(page.get_text("text")) for page in doc.pages()]
        outline = [(lvl, name, pg) for lvl, name, pg in doc.get_toc() if 1 <= pg <= len(pages)]
        meta_title = (doc.metadata or {}).get("title") or ""
    if not any(pages):
        raise NoTextError("no text layer found; scanned PDFs need OCR")
    fallback = source.stem if isinstance(source, Path) else "Untitled"
    book_title = title or meta_title.strip() or fallback

    if not outline:
        outline = [(1, book_title, 1)]

    # Start of every section as (page index, offset in that page), kept in outline order.
    starts: list[tuple[int, int]] = []
    previous = (0, 0)
    for _, name, pg in outline:
        page_index = max(pg - 1, previous[0])
        floor = previous[1] if page_index == previous[0] else 0
        offset = _heading_offset(pages[page_index], name, floor)
        previous = (page_index, offset)
        starts.append(previous)

    bounds = [*starts, (len(pages), 0)]
    sections: list[Section] = []
    first_page, first_offset = starts[0]
    front = _slice(pages, (0, 0), (first_page, first_offset))
    if front:
        sections.append(Section(FRONT_MATTER, FRONT_MATTER, 1, front))

    stack: list[tuple[int, str]] = []
    for (level, name, _), begin, end in zip(outline, starts, bounds[1:], strict=True):
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, name.strip()))
        segments = _slice(pages, begin, end)
        if segments:
            path = " > ".join(t for _, t in stack)
            sections.append(Section(name.strip(), path, level, segments))
    return ParsedBook(book_title, len(pages), tuple(sections))


def _slice(pages: list[str], begin: tuple[int, int], end: tuple[int, int]) -> tuple[PageText, ...]:
    """Text from `begin` up to `end` (page index, offset), split per page, blanks dropped."""
    segments: list[PageText] = []
    for index in range(begin[0], min(end[0] + 1, len(pages))):
        start = begin[1] if index == begin[0] else 0
        stop = end[1] if index == end[0] else len(pages[index])
        text = pages[index][start:stop].strip()
        if text:
            segments.append(PageText(index + 1, text))
    return tuple(segments)
