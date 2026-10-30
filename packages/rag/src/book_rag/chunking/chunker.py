"""Section-aware chunking: a chunk never crosses a section boundary and knows its pages."""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass

from book_rag.parsing import ParsedBook, Section

_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


@dataclass(frozen=True, slots=True)
class Chunk:
    book_title: str
    section_title: str
    section_path: str
    ordinal: int  # position in the book, from 0
    text: str
    page_start: int
    page_end: int
    section_index: int  # position of the section in `ParsedBook.sections`


def _sentences(text: str, max_chars: int) -> list[tuple[int, int]]:
    """(start, end) offsets of sentences; a sentence longer than `max_chars` is cut on spaces."""
    spans: list[tuple[int, int]] = []
    position = 0
    for piece in _SENTENCE_END.split(text):
        start = text.index(piece, position)
        position = start + len(piece)
        while len(piece) > max_chars:
            cut = piece.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            spans.append((start, start + cut))
            rest = piece[cut:]
            piece = rest.lstrip()
            start += cut + len(rest) - len(piece)
        if piece:
            spans.append((start, start + len(piece)))
    return spans


def _chunk_section(
    book_title: str,
    section: Section,
    section_index: int,
    ordinal: int,
    max_chars: int,
    overlap: int,
) -> list[Chunk]:
    text = ""
    page_starts: list[int] = []
    pages: list[int] = []
    for segment in section.segments:
        if text:
            text += " "
        page_starts.append(len(text))
        pages.append(segment.page)
        text += segment.text

    def page_at(offset: int) -> int:
        return pages[max(bisect_right(page_starts, offset) - 1, 0)]

    spans = _sentences(text, max_chars)
    chunks: list[Chunk] = []
    first = 0
    while first < len(spans):
        last = first
        while last + 1 < len(spans) and spans[last + 1][1] - spans[first][0] <= max_chars:
            last += 1
        start, end = spans[first][0], spans[last][1]
        chunks.append(
            Chunk(
                book_title,
                section.title,
                section.path,
                ordinal + len(chunks),
                text[start:end],
                page_at(start),
                page_at(end - 1),
                section_index,
            )
        )
        if last + 1 >= len(spans):
            break
        # Next chunk starts a few sentences back so context carries over, but always moves on.
        nxt = last + 1
        while nxt - 1 > first and spans[last][1] - spans[nxt - 1][0] <= overlap:
            nxt -= 1
        first = nxt
    return chunks


def chunk_book(book: ParsedBook, max_chars: int = 1200, overlap: int = 150) -> list[Chunk]:
    """Split every section of `book` into chunks of at most `max_chars` characters."""
    if max_chars <= 0 or not 0 <= overlap < max_chars:
        raise ValueError("need max_chars > 0 and 0 <= overlap < max_chars")
    chunks: list[Chunk] = []
    for index, section in enumerate(book.sections):
        chunks.extend(_chunk_section(book.title, section, index, len(chunks), max_chars, overlap))
    return chunks
