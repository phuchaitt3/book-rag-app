"""Regression gate for the answer eval in CI (#22).

`apps/api/tests/test_answer_eval.py` runs the harness (`evals/answer_eval.py`) with the fake
providers and, when EVAL_SCORES_OUT is set, writes its summary as JSON. This script compares that
summary to `evals/baseline.json`, prints a table (also to $GITHUB_STEP_SUMMARY when set) and exits 1
when a metric is worse than its baseline by more than the metric's tolerance, or when a sample size
changed (the fixture changed: re-record the baseline on purpose).

The scores are plumbing and regression scores: the fake providers and the scripted answers fix them,
so they show the harness and the retrieval path still work, not model quality.

  uv run python evals/ci_eval.py SCORES.json            # compare to evals/baseline.json
  uv run python evals/ci_eval.py SCORES.json --record   # rewrite the baseline values from SCORES
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

BASELINE = Path(__file__).resolve().parent / "baseline.json"


def compare(scores: Mapping[str, Any], baseline: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One row per baseline metric: name, baseline, current, n, ok, reason.

    A metric is `higher` (a drop is a regression) or `lower` (a rise is). It passes while it is
    within `tolerance` of the baseline on the good side or any distance on the better side.
    """
    rows: list[dict[str, Any]] = []
    for name, spec in baseline["metrics"].items():
        current = scores.get(name)
        n_key = spec.get("n_key")
        n_now = scores.get(n_key) if n_key else None
        reason = ""
        if current is None:
            reason = "missing from scores"
        elif n_key and n_now != spec["n"]:
            reason = f"n changed: {n_now} instead of {spec['n']}"
        elif spec["direction"] == "higher" and current < spec["value"] - spec["tolerance"]:
            reason = f"dropped below {spec['value']} - {spec['tolerance']}"
        elif spec["direction"] == "lower" and current > spec["value"] + spec["tolerance"]:
            reason = f"rose above {spec['value']} + {spec['tolerance']}"
        rows.append(
            {
                "metric": name,
                "baseline": spec["value"],
                "current": current,
                "tolerance": spec["tolerance"],
                "direction": spec["direction"],
                "n": n_now if n_key else scores.get("questions"),
                "ok": not reason,
                "reason": reason,
            }
        )
    return rows


def table(rows: list[dict[str, Any]]) -> str:
    head = "| Metric | Baseline | Current | Tolerance | n | Result |\n|---|---|---|---|---|---|\n"
    body = "".join(
        f"| {r['metric']} ({r['direction']} is better) | {r['baseline']} | {r['current']} | "
        f"{r['tolerance']} | {r['n']} | {'ok' if r['ok'] else 'FAIL: ' + r['reason']} |\n"
        for r in rows
    )
    return head + body


def record(scores: Mapping[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    for name, spec in baseline["metrics"].items():
        spec["value"] = scores[name]
        if spec.get("n_key"):
            spec["n"] = scores[spec["n_key"]]
    return baseline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("scores", type=Path)
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args(argv)
    scores = json.loads(args.scores.read_text(encoding="utf-8"))
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    if args.record:
        updated = record(scores, baseline)
        args.baseline.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")
    rows = compare(scores, baseline)
    text = "## Answer eval (fake providers, regression scores)\n\n" + table(rows)
    print(text)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    failed = [r for r in rows if not r["ok"]]
    if failed:
        print(f"{len(failed)} metric(s) regressed", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
