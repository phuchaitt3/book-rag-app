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
