"""Tests for the page-set cleaner (#299). Run: uv run pytest experiments/pages/test_clean.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from collect import clean, strip_templates


def test_nested_heading_keeps_text() -> None:
    assert strip_templates("{{g|{{xx-lớn|VI}}}}") == "VI"
    assert (
        strip_templates("{{c|{{g|{{xx-lớn|HỒI THỨ MƯỜI BA}}}}}}\nbody") == "HỒI THỨ MƯỜI BA\nbody"
    )


def test_no_text_templates_dropped() -> None:
    assert strip_templates("a {{rule}} b {{-}} c") == "a  b  c"


def test_named_params_ignored() -> None:
    assert strip_templates("{{g|size=120%|Tiết thứ hai}}") == "Tiết thứ hai"


def test_unbalanced_remnants_removed() -> None:
    assert "{{" not in strip_templates("x {{g|\ny")
    assert "}}" not in strip_templates("x }} y")


def test_clean_full_page() -> None:
    wt = (
        '<noinclude><pagequality level="4" user="u" /></noinclude>'
        "{{g|{{xx-lớn|VI}}}}\n\n'''Thân bài''' hai"
    )
    level, text = clean(wt)
    assert level == 4
    assert text == "VI\n\nThân bài hai"


def test_rule_widths_are_not_text() -> None:
    assert strip_templates("a{{vạch|6em}}{{vạch tùy chỉnh|sp|40|el|15}}b") == "ab"


def test_sic_keeps_the_printed_form() -> None:
    assert strip_templates("Nam-{{SIC|tuớc|tước}}") == "Nam-tuớc"


def test_page_end_hyphen_kept() -> None:
    assert strip_templates("quành{{nct}}") == "quành-"


def test_indent_marks_and_line_breaks() -> None:
    assert clean("a<br/>b\n:::''Mình''")[1] == "a\nb\nMình"


def test_footnotes_move_to_the_end() -> None:
    wt = "Ô-lí<ref>Thuận-hóa.</ref>, Hoan<ref>Nghệ-an.</ref>.\n\nHết"
    assert clean(wt)[1] == "Ô-lí, Hoan.\n\nHết\nThuận-hóa.\nNghệ-an."
