"""PreToolUse hook: stop a PR description from closing an issue by accident.

GitHub reads "close", "fix" or "resolve" (with -s, -d or -ed, optional colon) followed by `#n` as
a closing reference wherever it appears in a PR description, even in "Does not close #35".
Merging such a PR closes the issue. This hook refuses `gh pr create`, `gh pr edit` and
`gh pr merge` commands whose text has a closing keyword next to an issue reference, unless the
keyword starts a line ("Closes #12"), which reads as a deliberate closing line. Write
"Part of #n" for work that does not finish the issue.

This is a guardrail against mistakes, not a security boundary: an edit in the browser or a
command built at run time is not seen. It needs `python` on PATH.
"""

from __future__ import annotations

import json
import re
import sys

_PR_COMMAND = re.compile(r"\bgh(\.exe)?\b[^\n;&|]*\bpr\s+(create|edit|merge)\b", re.I)
# GitHub's closing keywords, then an issue reference: #n, owner/repo#n or an issue URL.
_CLOSING = re.compile(
    r"\b(clos(?:e[sd]?)|fix(?:e[sd])?|resolv(?:e[sd]?))\b:?\s+"
    r"((?:[\w.-]+/[\w.-]+)?#\d+|https://github\.com/\S+/issues/\d+)",
    re.I,
)
_LINE_START = re.compile(r"^[ \t>*+-]*$")


def check(command: str) -> str | None:
    """Return a refusal reason for `command`, or None when it may run."""
    if not _PR_COMMAND.search(command):
        return None
    bad: list[str] = []
    for match in _CLOSING.finditer(command):
        line_start = command.rfind("\n", 0, match.start()) + 1
        if not _LINE_START.match(command[line_start : match.start()]):
            bad.append(match.group(0))
    if not bad:
        return None
    found = ", ".join(f'"{text}"' for text in bad)
    return (
        f"GitHub closes the issue when this PR merges because of {found}, even in a sentence "
        'such as "does not close #n". Write "Part of #n" for work that does not finish the '
        'issue, or put "Closes #n" alone at the start of a line when it should close it.'
    )


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
    reason = check(command)
    if reason is not None:
        _deny(reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
