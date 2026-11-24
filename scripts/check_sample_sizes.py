"""Fail when README or docs state a measured number with no sample size nearby.

A "numeric claim" is a percentage ("92%"), a latency ("120 ms", "1.5 s") or a
named metric with a decimal value ("recall@5 0.83", "MRR = 0.61"). It needs a
sample-size marker in the same section (text between two "#"/"##" headings): "n=200",
"N = 1,000", "200 questions", "on 40 queries". One marker covers the numbers
reported in that section, as benchmark pages state n once.

Waive a section with `<!-- numcheck: ok: reason -->` on any of its lines; use it
for numbers that are not measurements (limits, targets, config values).

Scope (issue #303): README.md and docs/**/*.md except docs/adr, docs/design and
docs/operations. ADRs, design briefs and the runbook/SLO pages state decisions,
budgets, targets and alert thresholds, not measurements; measurements live in
docs/benchmarks and the README, which are in scope. Pass paths to check other
files. Code fences and HTML comments are skipped; heading lines are not claims.

Usage: python scripts/check_sample_sizes.py [PATH ...]   (stdlib only)
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable
from pathlib import Path

WAIVER = "numcheck: ok"
EXCLUDED_DIRS = ("docs/adr", "docs/design", "docs/operations")

_PERCENT = r"\d+(?:\.\d+)?\s?%(?!\s*(?:CI|confidence|bootstrap|interval))"
_LATENCY = r"\b\d+(?:[.,]\d+)?\s?(?:ms|milliseconds?|µs|seconds?)\b"
_METRIC = (
    r"\b(?:recall|precision|mrr|ndcg|hit[ -]rate|accuracy|f1|cer|wer)"
    r"(?:@\d+)?\s*(?:=|:|of|was|is|to)?\s*(?:0?\.\d+|1\.0+)\b"
)
CLAIM = re.compile(f"{_PERCENT}|{_LATENCY}|{_METRIC}", re.IGNORECASE)

_UNITS = (
    r"questions?|queries|query|samples?|requests?|runs?|pages?|chunks?|books?|"
    r"trials?|examples?|items?|documents?|docs|cases|passages?|prompts?|pairs|"
    r"turns?|sessions?|images?|rows?|users?|repeats?|repetitions?|measurements?|ones"
)
SAMPLE = re.compile(
    r"\bn\s*=\s*[\dN]"
    rf"|\b\d[\d,._]*\s*(?:x\s*)?(?:[\w-]+\s+){{0,3}}(?:{_UNITS})\b",
    re.IGNORECASE,
)
_COMMENT = re.compile(r"<!--.*?-->")


def default_files(root: Path) -> list[Path]:
    files = [root / "README.md"] if (root / "README.md").exists() else []
    for path in sorted((root / "docs").rglob("*.md")):
        rel = path.relative_to(root).as_posix()
        if not rel.startswith(tuple(d + "/" for d in EXCLUDED_DIRS)):
            files.append(path)
    return files


def sections(text: str) -> list[list[tuple[int, str]]]:
    """Split into sections (a heading starts one); drop code fences and comments.

    Returns lines as (line number, text). A waived section keeps a WAIVER line.
    """
    result: list[list[tuple[int, str]]] = [[]]
    in_fence = False
    for number, raw in enumerate(text.splitlines(), start=1):
        if raw.strip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        line = _COMMENT.sub("", raw)
        if re.match(r"#{1,2}\s", raw):
            result.append([])
            continue
        if WAIVER in raw:
            result[-1].append((number, WAIVER))
        result[-1].append((number, line))
    return result


def check_text(text: str) -> list[tuple[int, str]]:
    """Return (line number, line) for claims in a section with no sample size."""
    problems: list[tuple[int, str]] = []
    for section in sections(text):
        if any(line == WAIVER for _, line in section):
            continue
        if any(SAMPLE.search(line) for _, line in section):
            continue
        problems.extend((n, line.strip()) for n, line in section if CLAIM.search(line))
    return problems


def run(paths: Iterable[Path], root: Path) -> int:
    failures = 0
    for path in paths:
        try:
            shown = path.resolve().relative_to(root).as_posix()
        except ValueError:
            shown = path.as_posix()
        for number, line in check_text(path.read_text(encoding="utf-8")):
            print(f"{shown}:{number}: number without a sample size: {line[:100]}")
            failures += 1
    if failures:
        print(
            f"\n{failures} claim(s) need an n=, 'N questions' or similar in the same "
            f"section, or <!-- {WAIVER}: reason --> (scripts/check_sample_sizes.py)."
        )
    return 1 if failures else 0


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parent.parent
    paths = [Path(a) for a in argv] or default_files(root)
    return run(paths, root)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
