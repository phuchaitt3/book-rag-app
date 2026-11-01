import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "pr_close_guard", Path(__file__).with_name("pr_close_guard.py")
)
assert _spec and _spec.loader
pr_close_guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pr_close_guard)


@pytest.mark.parametrize(
    "body",
    [
        "Does not close #35 (the review continues).",
        "This fixes #12 in passing.",
        "resolved: #7",
        "Closes phuchaitt3/book-rag-app#35 later",
        "Not closing https://github.com/o/r/issues/9 yet, but fixes https://github.com/o/r/issues/9",
    ],
)
def test_closing_word_inside_a_sentence_is_refused(body: str) -> None:
    command = f'gh pr create --title t --body "Note. {body}"'
    reason = pr_close_guard.check(command)
    assert reason and "Part of #n" in reason


@pytest.mark.parametrize(
    "command",
    [
        'gh pr create --title t --body "Part of #35. Docs only."',
        "gh pr create --body-file b.md",
        "gh pr edit 9 --body 'Part of #35'",
        "gh issue comment 35 --body 'Does not close #35'",
        "git commit -m 'fix #3 in the parser'",
    ],
)
def test_other_commands_pass(command: str) -> None:
    assert pr_close_guard.check(command) is None


def test_closing_line_at_line_start_passes() -> None:
    command = "gh pr create --title t --body \"$(cat <<'EOF'\nWhat it does.\n\nCloses #12\nEOF\n)\""
    assert pr_close_guard.check(command) is None


def test_bullet_closing_line_passes() -> None:
    command = 'gh pr create --body "\n- Closes #12\n- Closes #13"'
    assert pr_close_guard.check(command) is None


def test_gh_with_flags_before_subcommand_is_checked() -> None:
    assert pr_close_guard.check('gh -R o/r pr edit 4 --body "does not close #4"')


@pytest.mark.parametrize(
    "command",
    [
        'gh pr create --title t --body "Closes #82. Adds the thing."',
        "gh pr create --title t -b 'Closes #82'",
        'gh pr create --body="Closes #82"',
    ],
)
def test_closing_keyword_right_after_the_body_quote_passes(command: str) -> None:
    assert pr_close_guard.check(command) is None


def test_keyword_later_in_a_one_line_body_is_still_refused() -> None:
    assert pr_close_guard.check('gh pr create --body "This does not close #82"')
