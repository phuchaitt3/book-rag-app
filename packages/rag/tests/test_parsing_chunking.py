import io
from pathlib import Path

import font_roboto
import pytest
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from book_rag.chunking import chunk_book
from book_rag.parsing import NoTextError, ParsedBook, parse_pdf

FONT = "Roboto"  # has Vietnamese glyphs; the base-14 fonts do not
pdfmetrics.registerFont(
    TTFont(FONT, str(Path(font_roboto.__file__).parent / "files" / "Roboto-Regular.ttf"))
)

SENTENCES = [
    "Việt Nam là một đất nước nằm ở Đông Nam Á.",
    "Đường đi khó nhưng ươm mầm hy vọng.",
    "Người nông dân gieo hạt vào mùa xuân.",
    "Sông Mê Kông chảy qua nhiều tỉnh phía nam.",
]


def _paragraph(seed: str, count: int = 12) -> str:
    return " ".join(f"{SENTENCES[i % len(SENTENCES)]} ({seed}{i})" for i in range(count))


Block = tuple[str, str]  # (heading, body)


def build_pdf(pages: list[list[Block]], toc: list[tuple[int, str, int]] | None = None) -> bytes:
    """One PDF page per entry. `toc` is the outline as (level, title, page), levels from 1."""
    buffer = io.BytesIO()
    canvas = Canvas(buffer, pageSize=A4)
    for number, blocks in enumerate(pages, start=1):
        for level, title, page in toc or []:
            if page == number:
                key = f"bookmark-{title}"
                canvas.bookmarkPage(key)
                canvas.addOutlineEntry(title, key, level=level - 1)
        y = 800.0
        for heading, body in blocks:
            if heading:
                canvas.setFont(FONT, 16)
                canvas.drawString(40, y, heading)
                y -= 26
            canvas.setFont(FONT, 11)
            for line in simpleSplit(body, FONT, 11, 515):
                canvas.drawString(40, y, line)
                y -= 15
            y -= 12
        canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def make_pdf(chapters: list[tuple[str, int, str]], *, outline: bool = True) -> bytes:
    """One chapter per page: (title, level, body)."""
    toc = [(lvl, title, i + 1) for i, (title, lvl, _) in enumerate(chapters)] if outline else None
    return build_pdf([[(title, body)] for title, _, body in chapters], toc)


@pytest.fixture
def book() -> ParsedBook:
    pdf = make_pdf(
        [
            ("Chương 1: Khởi đầu", 1, _paragraph("a")),
            ("Chương 2: Đồng bằng", 1, _paragraph("b")),
            ("Chương 3: Kết thúc", 1, _paragraph("c", 4)),
        ]
    )
    return parse_pdf(pdf, title="Sách thử")


def test_sections_come_from_the_outline(book: ParsedBook) -> None:
    assert [s.title for s in book.sections] == [
        "Chương 1: Khởi đầu",
        "Chương 2: Đồng bằng",
        "Chương 3: Kết thúc",
    ]
    assert book.page_count == 3
    assert "ươm mầm" in book.sections[0].segments[0].text  # Vietnamese survives extraction


def test_nested_outline_builds_a_path() -> None:
    pdf = make_pdf([("Phần I", 1, _paragraph("x", 2)), ("1.1 Mở đầu", 2, _paragraph("y", 2))])
    book = parse_pdf(pdf)
    assert book.sections[1].path == "Phần I > 1.1 Mở đầu"


def test_chunks_keep_book_section_and_page(book: ParsedBook) -> None:
    chunks = chunk_book(book, max_chars=300, overlap=60)
    assert len(chunks) > 3
    assert {c.book_title for c in chunks} == {"Sách thử"}
    for chunk in chunks:
        section = next(s for s in book.sections if s.title == chunk.section_title)
        pages = {seg.page for seg in section.segments}
        assert chunk.page_start in pages and chunk.page_end in pages
        assert len(chunk.text) <= 300
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))


def test_no_chunk_crosses_a_section_boundary(book: ParsedBook) -> None:
    for chunk in chunk_book(book, max_chars=300, overlap=60):
        section = next(s for s in book.sections if s.title == chunk.section_title)
        body = " ".join(seg.text for seg in section.segments)
        assert chunk.text in body


def test_two_sections_on_one_page_are_split_at_the_heading() -> None:
    pdf = build_pdf(
        [[("Mục A", "Nội dung của mục A."), ("Mục B", "Nội dung của mục B.")]],
        [(1, "Mục A", 1), (1, "Mục B", 1)],
    )
    book = parse_pdf(pdf)
    a, b = book.sections
    assert "mục A" in a.segments[0].text and "mục B" not in a.segments[0].text
    assert "mục B" in b.segments[0].text and "mục A" not in b.segments[0].text


def test_a_heading_text_quoted_earlier_on_the_page_does_not_cut_the_section() -> None:
    pdf = build_pdf(
        [[("Mục A", "Xem thêm Mục B ở phần sau."), ("Mục B", "Nội dung của mục B.")]],
        [(1, "Mục A", 1), (1, "Mục B", 1)],
    )
    a, b = parse_pdf(pdf).sections
    assert "Xem thêm Mục B ở phần sau." in a.segments[0].text
    assert "Xem thêm" not in b.segments[0].text


def test_overlap_repeats_trailing_sentences(book: ParsedBook) -> None:
    chunks = [
        c
        for c in chunk_book(book, max_chars=300, overlap=100)
        if c.section_title.endswith("Khởi đầu")
    ]
    assert len(chunks) >= 2
    tail = chunks[0].text.split(". ")[-1]
    assert tail in chunks[1].text


def test_pdf_without_outline_is_one_section() -> None:
    book = parse_pdf(
        make_pdf([("Tiêu đề", 1, _paragraph("z", 3))], outline=False), title="Một mạch"
    )
    assert [s.title for s in book.sections] == ["Một mạch"]
    assert chunk_book(book)


def test_text_before_the_first_heading_is_front_matter() -> None:
    pdf = build_pdf([[("", "Lời tựa ngắn.")], [("Chương 1", "Nội dung.")]], [(1, "Chương 1", 2)])
    book = parse_pdf(pdf)
    assert [s.title for s in book.sections] == ["(front matter)", "Chương 1"]


def test_scanned_pdf_without_text_is_rejected() -> None:
    with pytest.raises(NoTextError):
        parse_pdf(build_pdf([[]]))


def _scan_page(canvas: Canvas, *, full: bool = True, caption: str = "") -> None:
    from reportlab.lib.utils import ImageReader

    image = ImageReader(io.BytesIO(_PNG))
    if full:
        canvas.drawImage(image, 0, 0, width=595, height=842)
    else:
        canvas.drawImage(image, 40, 40, width=60, height=60)  # a small logo
    if caption:
        canvas.setFont(FONT, 11)
        canvas.drawString(40, 800, caption)
    canvas.showPage()


def _mixed_pdf(kinds: list[str]) -> bytes:
    """'text' = a full text page, 'scan' = a full-page image, 'scan+ocr' = image with text behind,
    'logo' = a thin page with a small image, 'blank' = nothing."""
    buffer = io.BytesIO()
    canvas = Canvas(buffer, pageSize=A4)
    for kind in kinds:
        if kind == "text":
            canvas.setFont(FONT, 11)
            for i, line in enumerate(simpleSplit(_paragraph("t"), FONT, 11, 515)):
                canvas.drawString(40, 800 - 15 * i, line)
            canvas.showPage()
        elif kind == "scan":
            _scan_page(canvas)
        elif kind == "scan+ocr":
            canvas.setFont(FONT, 11)
            for i, line in enumerate(simpleSplit(_paragraph("o"), FONT, 11, 515)):
                canvas.drawString(40, 800 - 15 * i, line)
            _scan_page(canvas)
        elif kind == "logo":
            _scan_page(canvas, full=False, caption="Chương 2")
        else:
            canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def _png() -> bytes:
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    row = bytes([0]) + bytes([200, 200, 200]) * 8
    ihdr = struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0)
    return (
        bytes([137])
        + b"PNG"
        + bytes([13, 10, 26, 10])
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(row * 8))
        + chunk(b"IEND", b"")
    )


_PNG = _png()


def test_text_book_has_no_flagged_pages() -> None:
    assert parse_pdf(_mixed_pdf(["text", "text"])).flagged_pages == ()


def test_scanned_pages_are_flagged_and_text_pages_still_ingest() -> None:
    book = parse_pdf(_mixed_pdf(["text", "scan", "text", "scan"]))
    assert book.flagged_pages == (2, 4)
    assert book.page_count == 4
    pages = {seg.page for sec in book.sections for seg in sec.segments}
    assert pages == {1, 3}


def test_thin_page_with_a_small_image_is_not_flagged() -> None:
    book = parse_pdf(_mixed_pdf(["text", "logo", "blank"]))
    assert book.flagged_pages == ()


def test_scan_with_a_text_layer_is_not_flagged() -> None:
    """The known limit of the first version: an already-OCR'd scan has characters."""
    assert parse_pdf(_mixed_pdf(["text", "scan+ocr"])).flagged_pages == ()


def test_every_page_flagged_is_rejected() -> None:
    with pytest.raises(NoTextError):
        parse_pdf(_mixed_pdf(["scan", "scan"]))


def test_long_sentence_is_cut_to_fit() -> None:
    pdf = make_pdf([("Dài", 1, "từ " * 400)])
    chunks = chunk_book(parse_pdf(pdf), max_chars=200, overlap=0)
    assert all(len(c.text) <= 200 for c in chunks) and len(chunks) > 3


@pytest.mark.parametrize("max_chars, overlap", [(0, 0), (100, 100), (100, -1)])
def test_bad_chunk_settings_are_rejected(book: ParsedBook, max_chars: int, overlap: int) -> None:
    with pytest.raises(ValueError):
        chunk_book(book, max_chars=max_chars, overlap=overlap)


def test_chunks_of_sections_sharing_a_path_keep_their_own_section_index() -> None:
    from book_rag.parsing import PageText, Section

    def section(page: int) -> Section:
        return Section("Phụ lục", "Phụ lục", 1, (PageText(page, "Một câu ngắn."),))

    chunks = chunk_book(ParsedBook("Sách", 2, (section(1), section(2))))
    assert [c.section_index for c in chunks] == [0, 1]
