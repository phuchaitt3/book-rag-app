"""PreToolUse hook: stop agents from merging pull requests that are the user's to merge.

Reads the hook JSON on stdin. For a Bash command that runs `gh pr merge` (or merges through
`gh api`), it refuses `--admin` always, and otherwise asks `gh pr diff --name-only` for the
changed files and refuses when any of them is on the user-merge list in CLAUDE.md. If the files
cannot be listed, or the hook itself fails on a command that mentions "merge", the merge is
refused.

This is a guardrail against mistakes, not a security boundary: an agent can still override it in
an untracked `.claude/settings.local.json`, and a push that adds a protected file after the check
is merged by `--auto` unseen. The hard gates are GitHub's required checks and the user-merge rule.
It needs `python` on PATH; without it the hook command errors and the gate is absent.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from collections.abc import Callable, Sequence

# Paths the user merges (CLAUDE.md, "Pull requests"). Any `.github/` file is refused: the
# risk-based exception there needs a judgment call, so the user (or a reviewer reading the
# diff) decides. Lockfiles are not listed: CLAUDE.md lets the reviewer merge a lockfile-only
# change after listing each changed package. README.md and other docs are ordinary files: the
# reviewer checks their claims against the code (CLAUDE.md). Compose files are not listed: the
# local dev stack is not deploy config (CLAUDE.md), and the reviewer checks it adds no secret
# value or unauthenticated port.
USER_MERGE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"^CLAUDE\.md$", "CLAUDE.md"),
    (r"^\.claude/", "agent settings and hooks (.claude/)"),
    (r"^\.github/", "anything under .github/"),
    (r"^infra/", "infra/"),
    (r"(^|/)Dockerfile[^/]*$", "deploy config (Dockerfile)"),
    (r"(^|/)\.dockerignore$", "deploy config (.dockerignore)"),
    (r"(^|/)(neon\.ts|vercel\.json)$", "deploy config"),
    (r"(^|/)\.env(?!\.example$)(\..*)?$", "secrets (.env)"),
    (r"\.(pem|key)$", "secrets (key file)"),
    (r"(^|/)credentials[^/]*\.json$", "secrets (credentials)"),
    (
        r"(^|/)(auth|authn|authz|permissions?|sessions?)(/|\.[a-z]+$)",
        "authentication/authorization",
    ),
    (r"^(LICENSE|SECURITY\.md)$", "licensing and security policy"),
)

_SEGMENT_SPLIT = re.compile(r"&&|\|\||[;|&\n()`]")
_API_MERGE = re.compile(r"\bgh(\.exe)?\s+api\b.*(merge|enablePullRequestAutoMerge)", re.I | re.S)
# `gh` flags before the subcommand that take a value (`gh -R o/r pr merge 9`).
_GH_GLOBAL_VALUE_FLAGS = {"-R", "--repo", "--hostname"}
# Flags of `gh pr merge` that take a value, so the value is not mistaken for the PR argument.
_VALUE_FLAGS = {
    "-b",
    "--body",
    "-F",
    "--body-file",
    "-t",
    "--subject",
    "-R",
    "--repo",
    "--match-head-commit",
    "-A",
    "--author-email",
}

FilesFn = Callable[[Sequence[str]], list[str]]


def gh_changed_files(pr_args: Sequence[str]) -> list[str]:
    """Return the files a PR changes; raise RuntimeError when gh cannot say."""
    cmd = ["gh", "pr", "diff", *pr_args, "--name-only"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"could not run gh: {exc}") from exc
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"gh exited with {result.returncode}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _is_gh(token: str) -> bool:
    name = token.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name in ("gh", "gh.exe")


def _gh_merge_args(tokens: Sequence[str]) -> list[str] | None:
    """Arguments after `gh [global flags] pr merge`, or None if `tokens` is not that."""
    for i, token in enumerate(tokens):
        if not _is_gh(token):
            continue
        j = i + 1
        while j < len(tokens) and tokens[j].startswith("-"):
            j += 2 if tokens[j] in _GH_GLOBAL_VALUE_FLAGS else 1
        if tokens[j : j + 2] == ["pr", "merge"]:
            return list(tokens[j + 2 :])
    return None


def _merge_segments(command: str) -> list[list[str]]:
    """Token lists for each `gh pr merge ...` in a shell command.

    Looks through chains (`&&`, `;`, `|`), `$(...)`, backticks and quoted `-c` arguments.
    """
    found: list[list[str]] = []
    for segment in _SEGMENT_SPLIT.split(command.replace("$(", ";")):
        try:
            tokens = shlex.split(segment, posix=True)
        except ValueError:
            tokens = segment.split()
        args = _gh_merge_args(tokens)
        if args is not None:
            found.append(args)
        for token in tokens:
            if " " in token and "merge" in token:
                found.extend(_merge_segments(token))
    return found


def _pr_args(merge_args: Sequence[str]) -> list[str]:
    """The PR selector and --repo, if any, to pass on to `gh pr diff`."""
    selector: list[str] = []
    repo: list[str] = []
    skip = False
    for i, arg in enumerate(merge_args):
        if skip:
            skip = False
            continue
        if arg in ("-R", "--repo") and i + 1 < len(merge_args):
            repo = ["--repo", merge_args[i + 1]]
            skip = True
        elif arg.startswith("--repo="):
            repo = ["--repo", arg.split("=", 1)[1]]
        elif arg in _VALUE_FLAGS:
            skip = True
        elif not arg.startswith("-") and not selector:
            selector = [arg]
    return [*selector, *repo]


def user_merge_hits(files: Sequence[str]) -> list[tuple[str, str]]:
    """(file, reason) for every changed file on the user-merge list."""
    hits: list[tuple[str, str]] = []
    for name in files:
        normalized = name.replace("\\", "/")
        for pattern, reason in USER_MERGE_PATTERNS:
            if re.search(pattern, normalized, flags=re.IGNORECASE):
                hits.append((name, reason))
                break
    return hits


def check(command: str, files_fn: FilesFn = gh_changed_files) -> str | None:
    """Return a refusal reason for `command`, or None when it may run."""
    if _API_MERGE.search(command):
        return (
            "Merging through `gh api` skips the merge gate. "
            "Use `gh pr merge`, and only on PRs that are not the user's to merge."
        )
    for merge_args in _merge_segments(command):
        if any(a == "--admin" or a.startswith("--admin=") for a in merge_args):
            return (
                "`gh pr merge --admin` bypasses the protect-main ruleset "
                "and is never allowed for agents."
            )
        pr_args = _pr_args(merge_args)
        try:
            files = files_fn(pr_args)
        except RuntimeError as exc:
            return f"Could not list the PR's files, so the merge is refused (fails closed): {exc}"
        hits = user_merge_hits(files)
        if hits:
            lines = "\n".join(f"  - {name}: {reason}" for name, reason in hits)
            return (
                'This PR touches paths the user merges (CLAUDE.md, "Pull requests"):\n'
                f"{lines}\n"
                "Mark the Review queue row `ready for user` instead of merging."
            )
    return None


def _deny(reason: str) -> None:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        },
        sys.stdout,
    )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
        return 0
    tool_input = payload.get("tool_input")
    command = str(tool_input.get("command", "")) if isinstance(tool_input, dict) else ""
    if "merge" not in command.lower():
        return 0
    try:
        reason = check(command)
    except Exception as exc:  # fail closed: an exit code other than 0 or 2 would let it through
        reason = f"The merge gate failed ({type(exc).__name__}: {exc}), so the merge is refused."
    if reason is not None:
        _deny(reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
