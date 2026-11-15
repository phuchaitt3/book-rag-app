"""Reading image-only PDF pages: the `PageReader` interface and page rendering.

See docs/design/brief-image-pages.md. A reader turns the image of one page into text; the page
is rendered with pypdfium2 (already the parser), one bitmap at a time.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Protocol

import pypdfium2 as pdfium

RENDER_DPI = 300  # the resolution Tesseract is tuned for; a measurable parameter (#273)


class PageReadError(Exception):
    """One page could not be rendered or read. Permanent for that page: the book goes on
    without it, and a later run tries the page again."""


class PageReader(Protocol):
    """Turns the image (PPM bytes) of one page into text.

    `name` and `version` identify the reader in the stored result, so a change of reader or
    settings is a new `version`, not a schema change. `read` blocks; run it in a thread.
    """

    name: str
    version: str

    def read(self, image: bytes) -> str: ...


@dataclass(frozen=True, slots=True)
class RenderedPage:
    page: int  # 1-based
    image: bytes | None
    error: str | None = None


def _to_ppm(bitmap: pdfium.PdfBitmap) -> bytes:
    """A binary PPM (P6) of the bitmap. Tesseract reads it; no imaging library is needed."""
    width, height, stride, channels = bitmap.width, bitmap.height, bitmap.stride, bitmap.n_channels
    raw = bytes(bitmap.buffer)
    rows = []
    for y in range(height):
        row = raw[y * stride : y * stride + width * channels]
        if channels == 3:
            rows.append(row)
        else:  # drop the extra (alpha or padding) channel
            rows.append(b"".join(row[i : i + 3] for i in range(0, len(row), channels)))
    return f"P6 {width} {height} 255\n".encode("ascii") + b"".join(rows)


def render_pages(
    source: bytes, pages: Iterable[int], dpi: int = RENDER_DPI
) -> Iterator[RenderedPage]:
    """Render the 1-based `pages` of a PDF to PPM, one at a time (only one bitmap is alive).

    A page that fails to render yields an entry with `error` set; the others still render.
    """
    doc = pdfium.PdfDocument(source)
    try:
        for number in pages:
            try:
                if not 1 <= number <= len(doc):
                    raise PageReadError(f"page {number} is not in the PDF")
                page = doc[number - 1]
                try:
                    bitmap = page.render(scale=dpi / 72, rev_byteorder=True)  # RGB order
                    rendered = RenderedPage(number, _to_ppm(bitmap))
                finally:
                    page.close()
                yield rendered
            except Exception as exc:  # pdfium raises PdfiumError and others on a bad page
                yield RenderedPage(number, None, f"{type(exc).__name__}: {exc}")
    finally:
        doc.close()
