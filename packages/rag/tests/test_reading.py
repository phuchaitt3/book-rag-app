import shutil

import pytest
from test_parsing_chunking import _mixed_pdf

from book_rag.parsing import NoTextError, parse_pdf
from book_rag.reading import FakePageReader, PageReadError, TesseractReader, render_pages


def test_read_text_replaces_the_layer_of_flagged_pages_only() -> None:
    pdf = _mixed_pdf(["text", "scan", "text", "scan"])
    book = parse_pdf(pdf, read_text={2: "Phụ lục ệ ữ ơ", 4: "Trang cuối"})
    assert book.flagged_pages == (2, 4)
    segments = {seg.page: seg.text for sec in book.sections for seg in sec.segments}
    assert set(segments) == {1, 2, 3, 4}
    assert "Phụ lục ệ ữ ơ" in segments[2] and "Trang cuối" in segments[4]


def test_all_flagged_book_needs_read_text() -> None:
    pdf = _mixed_pdf(["scan", "scan"])
    with pytest.raises(NoTextError):
        parse_pdf(pdf)
    with pytest.raises(NoTextError):
        parse_pdf(pdf, read_text={})
    assert parse_pdf(pdf, check_text=False).flagged_pages == (1, 2)
    book = parse_pdf(pdf, read_text={1: "một", 2: "hai"})
    assert [seg.page for sec in book.sections for seg in sec.segments] == [1, 2]


def test_render_pages_yields_an_image_per_page_and_reports_a_bad_page() -> None:
    pdf = _mixed_pdf(["text", "scan"])
    pages = list(render_pages(pdf, [2, 9], dpi=36))
    assert pages[0].image is not None and pages[0].image.startswith(b"P6 ")
    assert pages[1].image is None and pages[1].error


def test_fake_reader_is_scripted() -> None:
    reader = FakePageReader(fail_on=2)
    assert reader.read(b"x")
    with pytest.raises(PageReadError):
        reader.read(b"x")
    assert reader.calls == 2


def test_tesseract_reader_without_the_binary_raises_file_not_found() -> None:
    with pytest.raises(FileNotFoundError):
        TesseractReader(command="tesseract-binary-that-does-not-exist").read(b"x")


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract binary not installed")
def test_tesseract_reads_a_rendered_page() -> None:
    page = next(render_pages(_mixed_pdf(["scan"]), [1], dpi=100))
    assert page.image is not None
    assert isinstance(TesseractReader(languages="eng").read(page.image), str)
