"""Build a PDF of Việt Nam sử lược, Quyển I from the fetched HTML text (fallback for fetch_pdf.py).

Used when Wikisource's PDF export is down (HTTP 503 on 2026-11-24, #291). The text and the
section titles are those of `experiments/book-testset/fetch_book.py` (run it first); one PDF
page per printed page, a bookmark per section, so the app's parser finds the same sections. It
is NOT the PDF of the earlier runs: its chunk count and page numbers differ, so a result from
it says so.

  uv run python experiments/e2e/build_pdf_from_html.py  # -> data/vsl-html.pdf
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Flowable, PageBreak, Paragraph, SimpleDocTemplate

HERE = Path(__file__).parent
BOOK = HERE.parent / "book-testset" / "data" / "book.json"
OUT = HERE / "data" / "vsl-html.pdf"
FONT = Path("C:/Windows/Fonts/arial.ttf")


class Mark(Flowable):
    """A zero-size flowable that adds a bookmark and an outline entry at this page."""

    def __init__(self, title: str, level: int, key: str) -> None:
        super().__init__()
        self.title, self.level, self.key = title, level, key
        self.width = self.height = 0

    def draw(self) -> None:
        self.canv.bookmarkPage(self.key)
        self.canv.addOutlineEntry(self.title, self.key, level=self.level, closed=False)


def main() -> None:
    pdfmetrics.registerFont(TTFont("Arial", str(FONT)))
    style = ParagraphStyle("body", fontName="Arial", fontSize=10, leading=13)
    book: dict[str, Any] = json.loads(BOOK.read_text(encoding="utf-8"))
    story: list[Flowable] = []
    prev_level = -1
    first = True
    for n, section in enumerate(book["sections"]):
        level = min(max(int(section["level"]) - 1, 0), prev_level + 1)  # no skipped levels
        prev_level = level
        mark = Mark(section["title"], level, f"s{n}")
        for segment in section["segments"]:
            if not first:
                story.append(PageBreak())
            first = False
            if mark is not None:
                story.append(mark)
                mark = None
            text = segment["text"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            story.append(Paragraph(text, style))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(OUT), pagesize=A4).build(story)
    data = OUT.read_bytes()
    print(f"{OUT}: {len(data):,} bytes, sha256 {hashlib.sha256(data).hexdigest()}")


if __name__ == "__main__":
    main()
