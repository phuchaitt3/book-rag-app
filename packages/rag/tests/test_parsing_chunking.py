import pymupdf
import pytest

from book_rag.chunking import chunk_book
from book_rag.parsing import NoTextError, ParsedBook, parse_pdf

SENTENCES = [
    "Việt Nam là một đất nước nằm ở Đông Nam Á.",
    "Đường đi khó nhưng ươm mầm hy vọng.",
    "Người nông dân gieo hạt vào mùa xuân.",
    "Sông Mê Kông chảy qua nhiều tỉnh phía nam.",
]


def _paragraph(seed: str, count: int = 12) -> str:
    return " ".join(f"{SENTENCES[i % len(SENTENCES)]} ({seed}{i})" for i in range(count))


def make_pdf(chapters: list[tuple[str, int, str]], *, outline: bool = True) -> bytes:
    """One chapter per page: (title, level, body). Text is laid out with MuPDF's own fonts."""
    doc = pymupdf.open()
    for title, _, body in chapters:
        page = doc.new_page()
        page.insert_htmlbox(pymupdf.Rect(40, 40, 555, 800), f"<h2>{title}</h2><p>{body}</p>")
    if outline:
        doc.set_toc([[lvl, title, i + 1] for i, (title, lvl, _) in enumerate(chapters)])
    data = doc.tobytes()
    doc.close()
    return data


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
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_htmlbox(
        pymupdf.Rect(40, 40, 555, 800),
        "<h2>Mục A</h2><p>Nội dung của mục A.</p><h2>Mục B</h2><p>Nội dung của mục B.</p>",
    )
    doc.set_toc([[1, "Mục A", 1], [1, "Mục B", 1]])
    book = parse_pdf(doc.tobytes())
    a, b = book.sections
    assert "mục A" in a.segments[0].text and "mục B" not in a.segments[0].text
    assert "mục B" in b.segments[0].text and "mục A" not in b.segments[0].text


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
    doc = pymupdf.open()
    doc.new_page().insert_htmlbox(pymupdf.Rect(40, 40, 555, 800), "<p>Lời tựa ngắn.</p>")
    doc.new_page().insert_htmlbox(
        pymupdf.Rect(40, 40, 555, 800), "<h2>Chương 1</h2><p>Nội dung.</p>"
    )
    doc.set_toc([[1, "Chương 1", 2]])
    book = parse_pdf(doc.tobytes())
    assert [s.title for s in book.sections] == ["(front matter)", "Chương 1"]


def test_scanned_pdf_without_text_is_rejected() -> None:
    doc = pymupdf.open()
    doc.new_page()
    with pytest.raises(NoTextError):
        parse_pdf(doc.tobytes())


def test_long_sentence_is_cut_to_fit() -> None:
    pdf = make_pdf([("Dài", 1, "từ " * 400)])
    chunks = chunk_book(parse_pdf(pdf), max_chars=200, overlap=0)
    assert all(len(c.text) <= 200 for c in chunks) and len(chunks) > 3


@pytest.mark.parametrize("max_chars, overlap", [(0, 0), (100, 100), (100, -1)])
def test_bad_chunk_settings_are_rejected(book: ParsedBook, max_chars: int, overlap: int) -> None:
    with pytest.raises(ValueError):
        chunk_book(book, max_chars=max_chars, overlap=overlap)
