import importlib.util
from collections.abc import Sequence
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "merge_gate", Path(__file__).with_name("merge_gate.py")
)
assert _spec and _spec.loader
merge_gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(merge_gate)


def files(*names: str):
    def fn(_args: Sequence[str]) -> list[str]:
        return list(names)

    return fn


def test_claude_md_is_refused_with_file_name() -> None:
    reason = merge_gate.check("gh pr merge 9 --auto --squash", files("CLAUDE.md", "README.md"))
    assert reason and "CLAUDE.md" in reason


def test_api_only_pr_passes() -> None:
    assert (
        merge_gate.check(
            "gh pr merge 7 --squash", files("apps/api/src/x.py", "apps/api/tests/t.py")
        )
        is None
    )


@pytest.mark.parametrize(
    "command",
    [
        "gh pr merge 7 --admin --squash",
        "gh pr merge --admin 7",
        "cd x && gh pr merge 7 --squash --admin",
    ],
)
def test_admin_always_refused(command: str) -> None:
    reason = merge_gate.check(command, files("apps/api/src/x.py"))
    assert reason and "--admin" in reason


@pytest.mark.parametrize(
    "path",
    [
        "uv.lock",
        "apps/web/pnpm-lock.yaml",
        "infra/main.tf",
        ".github/workflows/ci.yml",
        ".github/CODEOWNERS",
        "apps/api/Dockerfile",
        "docker-compose.yml",
        ".env",
        "certs/server.pem",
        "apps/api/src/book_rag_api/auth/session.py",
        ".claude/hooks/merge_gate.py",
        "README.md",
    ],
)
def test_user_merge_paths_refused(path: str) -> None:
    assert merge_gate.check("gh pr merge 5 --squash", files("apps/api/x.py", path))


@pytest.mark.parametrize(
    "path",
    [
        "apps/api/src/book_rag_api/author.py",
        "packages/rag/src/x.py",
        "apps/web/README.md",
        ".env.example",
    ],
)
def test_ordinary_paths_pass(path: str) -> None:
    assert merge_gate.check("gh pr merge 5 --squash", files(path)) is None


def test_chained_command_is_still_checked() -> None:
    assert merge_gate.check("cd repo && gh pr merge 9 --squash", files("CLAUDE.md"))


def test_non_merge_commands_pass_without_calling_gh() -> None:
    def boom(_args: Sequence[str]) -> list[str]:
        raise AssertionError("gh must not be called")

    assert merge_gate.check("gh pr create --title x", boom) is None
    assert merge_gate.check("gh pr view 9", boom) is None


def test_gh_failure_fails_closed() -> None:
    def fail(_args: Sequence[str]) -> list[str]:
        raise RuntimeError("no network")

    reason = merge_gate.check("gh pr merge 9 --squash", fail)
    assert reason and "refused" in reason


def test_gh_api_merge_refused() -> None:
    assert merge_gate.check("gh api -X PUT repos/o/r/pulls/9/merge", files("a.py"))


def test_pr_selector_and_repo_are_passed_on() -> None:
    seen: list[list[str]] = []

    def fn(args: Sequence[str]) -> list[str]:
        seen.append(list(args))
        return []

    merge_gate.check("gh pr merge --squash -b 'note' --repo o/r 12", fn)
    assert seen == [["12", "--repo", "o/r"]]
