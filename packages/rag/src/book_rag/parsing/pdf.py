"""Text PDF parsing with pypdfium2 (BSD/Apache). Sections come from the PDF outline (bookmarks).

A PDF without an outline becomes one section. A page with a thin text layer that is mostly
covered by an image (a scan) is flagged in `ParsedBook.flagged_pages`; no model runs to decide
that. Reading those pages is a later step (docs/design/brief-image-pages.md): the caller passes
the text a reader produced as `read_text` and it replaces the thin text layer of those pages.
Without `read_text` (no reader configured), a PDF whose every page is flagged, or that has no
text at all, raises `NoTextError`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw

from book_rag.parsing.models import PageText, ParsedBook, Section

FRONT_MATTER = "(front matter)"

# Detector thresholds (proposal of the brief; tuning on labelled pages is #273).
THIN_TEXT_CHARS = 50  # fewer normalised text-layer characters than this is thin
IMAGE_COVERAGE = 0.5  # image objects covering more than this share of the page area


class NoTextError(ValueError):
    """The PDF has no extractable text, so it is probably a scan."""


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _norm_lines(text: str) -> tuple[str, frozenset[int]]:
    """`_norm(text)` plus the offsets in it where a line of the original begins."""
    parts: list[str] = []
    starts: set[int] = set()
    length = 0
    for line in text.splitlines():
        line = _norm(line)
        if not line:
            continue
        if parts:
            length += 1  # the joining space
        starts.add(length)
        parts.append(line)
        length += len(line)
    return " ".join(parts), frozenset(starts)


def _heading_offset(
    page_text: str, title: str, after: int, line_starts: frozenset[int] = frozenset()
) -> int:
    """Where the heading `title` starts in `page_text` (at or after `after`), else `after`.

    A match that begins a line wins over an earlier one inside a sentence (a quote, a running
    header); with no such match, the first one is used.
    """
    needle = _norm(title)
    if not needle:
        return after
    first = page_text.find(needle, after)
    index = first
    while index >= 0 and index not in line_starts:
        index = page_text.find(needle, index + 1)
    if index >= 0:
        return index
    return first if first >= 0 else after


def _image_coverage(page: pdfium.PdfPage) -> float:
    """Share (0..1) of the page area covered by image objects, overlaps counted once per image
    and the total capped at 1."""
    width, height = page.get_size()
    area = width * height
    if area <= 0:
        return 0.0
    covered = 0.0
    for obj in page.get_objects(filter=[pdfium_raw.FPDF_PAGEOBJ_IMAGE]):
        left, bottom, right, top = obj.get_bounds()
        w = min(right, width) - max(left, 0.0)
        h = min(top, height) - max(bottom, 0.0)
        if w > 0 and h > 0:
            covered += w * h
    return float(min(covered / area, 1.0))


def needs_reading(text: str, coverage: float) -> bool:
    """A page is flagged when its text layer is thin and an image covers most of it."""
    return len(text) < THIN_TEXT_CHARS and coverage > IMAGE_COVERAGE


def parse_pdf(
    source: Path | bytes,
    title: str | None = None,
    read_text: Mapping[int, str] | None = None,
    *,
    check_text: bool = True,
) -> ParsedBook:
    """Parse a PDF into sections of page-tagged text.

    `read_text` maps a 1-based flagged page to the text a reader found on it; None means no
    reader is configured. `check_text=False` skips the "no text" check, for the first pass that
    only finds the flagged pages.
    """
    doc = pdfium.PdfDocument(source)
    try:
        pages: list[str] = []
        flagged: list[int] = []
        line_starts: list[frozenset[int]] = []
        for page in doc:
            textpage = page.get_textpage()
            text, heads = _norm_lines(textpage.get_text_bounded())
            number = len(pages) + 1  # 1-based number of the page being added
            if needs_reading(text, _image_coverage(page)):
                flagged.append(number)
                if read_text is not None and number in read_text:
                    text, heads = _norm_lines(read_text[number])
            pages.append(text)
            line_starts.append(heads)
            textpage.close()
            page.close()
        outline = [
            (mark.level + 1, mark.get_title(), index + 1)
            for mark in doc.get_toc()
            if (dest := mark.get_dest()) is not None
            and (index := dest.get_index()) is not None
            and 0 <= index < len(pages)
        ]
        meta_title = doc.get_metadata_value("Title")
    finally:
        doc.close()
    if not pages:
        raise NoTextError("the PDF has no pages")
    if check_text and (not any(pages) or (read_text is None and len(flagged) == len(pages))):
        raise NoTextError("no usable text layer found; scanned PDFs need OCR")
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
        offset = _heading_offset(pages[page_index], name, floor, line_starts[page_index])
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
    return ParsedBook(book_title, len(pages), tuple(sections), tuple(flagged))


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
