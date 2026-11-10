"""Fetch Việt Nam sử lược, Quyển I, from vi.wikisource and chunk it as the app does (#177).

Writes, under OUT_DIR (default: experiments/book-testset/data, git-ignored):
  pages/<n>.html   the rendered chapter pages, cached so a rerun does not refetch
  book.json        the book as `book_rag.parsing.ParsedBook` (one section per chapter)
  chunks.jsonl     `book_rag.chunking.chunk_book(book)` with the app's defaults

The text is Trần Trọng Kim's (died 1953), public domain in Vietnam; the transcription
is the proofread one on Wikisource. Run from the repository root:

  uv run python experiments/book-testset/fetch_book.py
"""

from __future__ import annotations

import json
import os
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import asdict
from html.parser import HTMLParser
from pathlib import Path

from book_rag.chunking import chunk_book
from book_rag.parsing import PageText, ParsedBook, Section

API = "https://vi.wikisource.org/w/api.php"
ROOT = "Việt Nam sử lược/Quyển I"
USER_AGENT = "book-rag-app-testset/0.1 (https://github.com/phuchaitt3/book-rag-app)"
OUT = Path(os.environ.get("OUT_DIR", Path(__file__).parent / "data"))

# Reading order of Quyển I. The bibliography is left out (a list of titles, not prose).
ROMAN = [
    "I",
    "II",
    "III",
    "IV",
    "V",
    "VI",
    "VII",
    "VIII",
    "IX",
    "X",
    "XI",
    "XII",
    "XIII",
    "XIV",
    "XV",
]
CHAPTERS = (
    ["Tựa", "Nước Việt Nam"]
    + [f"Phần I/Chương {r}" for r in ROMAN[:4]]
    + [f"Phần II/Chương {r}" for r in ROMAN[:6]]
    + [f"Phần III/Chương {r}" for r in ROMAN[:15]]
    + ["Phần III/Phụ lục"]
)

# Elements whose text is not book prose: styles, page-number markers, footnote marks and lists.
SKIP_CLASSES = {"ws-noexport", "reference", "references", "reflist", "mw-references-wrap"}
BLOCK_TAGS = {"p", "div", "li", "br", "tr", "h1", "h2", "h3", "h4", "dd", "dt"}
CJK = re.compile(r"[⺀-鿿豈-﫿]+")


def api_get(**params: str) -> dict:
    url = API + "?" + urllib.parse.urlencode({**params, "format": "json", "formatversion": "2"})
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


class PageSplitter(HTMLParser):
    """Collects the text of `.prp-pages-output`, split at each printed-page marker."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pages: list[tuple[int, list[str]]] = []
        self._stack: list[tuple[str, bool]] = []  # (tag, skipped)
        self._in_body = 0  # depth inside .prp-pages-output
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        classes = set((a.get("class") or "").split())
        if "pagenum" in classes and a.get("data-page-number"):
            number = a["data-page-number"] or ""
            index = int(a.get("data-page-index") or 0)
            self.pages.append((int(number) if number.isdigit() else -index, []))
        if tag in {"br"}:
            self._text("\n")
            return
        skipped = tag in {"style", "script", "sup"} or bool(classes & SKIP_CLASSES)
        if "prp-pages-output" in classes or self._in_body:
            self._in_body += 1
        self._stack.append((tag, skipped))
        self._skip += skipped
        if tag in BLOCK_TAGS:
            self._text("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "br" or not self._stack:
            return
        while self._stack:
            t, skipped = self._stack.pop()
            self._skip -= skipped
            if self._in_body:
                self._in_body -= 1
            if t == tag:
                break
        if tag in BLOCK_TAGS:
            self._text("\n")

    def handle_data(self, data: str) -> None:
        self._text(data)

    def _text(self, data: str) -> None:
        if self._in_body and not self._skip and self.pages:
            self.pages[-1][1].append(data)


def clean(text: str) -> str:
    """One page's text: Han characters dropped (they repeat the Vietnamese), spaces collapsed."""
    text = unicodedata.normalize("NFC", text).replace("​", "")
    lines = []
    for line in text.splitlines():
        line = CJK.sub("", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    return " ".join(lines)


def fetch(cache: Path, title: str) -> tuple[str, str]:
    """(section title from the page header, rendered HTML), cached on disk."""
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / (re.sub(r"[^\w]+", "_", title) + ".json")
    if not path.exists():
        parsed = api_get(action="parse", page=f"{ROOT}/{title}", prop="text|wikitext")["parse"]
        path.write_text(json.dumps(parsed, ensure_ascii=False), encoding="utf-8")
        time.sleep(1.0)  # polite to Wikisource
    parsed = json.loads(path.read_text(encoding="utf-8"))
    m = re.search(r"\|\s*phần\s*=\s*(.+)", parsed["wikitext"])
    heading = m.group(1).strip() if m else title.rsplit("/", 1)[-1]
    return heading, parsed["text"]


def main() -> None:
    sections = []
    for title in CHAPTERS:
        heading, html = fetch(OUT / "pages", title)
        splitter = PageSplitter()
        splitter.feed(html)
        segments = tuple(
            PageText(page, text)
            for page, parts in splitter.pages
            if (text := clean("".join(parts)))
        )
        if not segments:
            raise SystemExit(f"no text found in {title}")
        part = title.split("/")[0] if "/" in title else ""
        path = " > ".join(p for p in ("Quyển I", part, heading) if p)
        sections.append(Section(heading, path, 2 if part else 1, segments))
    pages = [s.page for sec in sections for s in sec.segments if s.page > 0]
    book = ParsedBook("Việt Nam sử lược, Quyển I", max(pages), tuple(sections))
    chunks = chunk_book(book)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "book.json").write_text(
        json.dumps(asdict(book), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    with (OUT / "chunks.jsonl").open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(asdict(c), ensure_ascii=False) + "\n")
    chars = sum(len(s.text) for sec in sections for s in sec.segments)
    print(f"{len(sections)} sections, {chars:,} characters, {len(chunks)} chunks -> {OUT}")


if __name__ == "__main__":
    main()
