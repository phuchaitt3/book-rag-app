"""Summarise a real-LLM answer-eval run with 95% bootstrap intervals (#285).

Reads the per-question rows that `evals/answer_eval.py` wrote and computes, over the questions,
Hit@1, Hit@5, MRR@6 (rank of the evidence sentence among the cited chunks), cited-answer hit,
citation validity, the share of answers with no `[n]` marker, the false-abstain rate, the mean
token F1 and reference recall, and the error counts. Intervals: bootstrap, 10,000 resamples of
the questions, seed 285. A row that abstained has no rank and counts as a miss, as in the harness.

  uv run python experiments/e2e/real_llm_report.py experiments/e2e/results/answer-eval-<label>.json
"""

from __future__ import annotations

import json
import random
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

SEED = 285
RESAMPLES = 10_000


def interval(values: Sequence[float], seed: int = SEED, reps: int = RESAMPLES) -> list[float]:
    """Percentile bootstrap 95% interval of the mean, in the units of `values`."""
    n = len(values)
    if not n:
        return []
    rng = random.Random(seed)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(reps))
    return [means[int(0.025 * reps)], means[int(0.975 * reps)]]


def stat(
    rows: Sequence[dict[str, Any]], value: Callable[[dict[str, Any]], float]
) -> dict[str, Any]:
    values = [value(r) for r in rows]
    if not values:
        return {"n": 0}
    low, high = interval(values)
    return {"n": len(values), "mean": sum(values) / len(values), "ci95": [low, high]}


def summarise(results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    answerable = [r for r in results if r["answerable"]]
    evid = [r for r in answerable if "citation_rank" in r]
    streamed = [r for r in results if "citation_valid" in r]
    ref = [r for r in answerable if "token_f1" in r]

    def rank(r: dict[str, Any]) -> int:
        return int(r["citation_rank"] or 99)

    return {
        "questions": len(results),
        "format_errors": sum(r["format_error"] is not None for r in results),
        "stream_errors": sum(bool(r["stream_error"]) for r in results),
        "hit@1": stat(evid, lambda r: rank(r) <= 1),
        "hit@5": stat(evid, lambda r: rank(r) <= 5),
        "hit@6": stat(evid, lambda r: rank(r) <= 6),
        "mrr@6": stat(evid, lambda r: 1 / rank(r) if rank(r) <= 6 else 0.0),
        "cited_answer_hit": stat(evid, lambda r: bool(r["cited_answer_hit"])),
        "citation_valid": stat(streamed, lambda r: bool(r["citation_valid"])),
        "no_marker": stat(streamed, lambda r: r["markers"] == 0),
        "false_abstain": stat(answerable, lambda r: bool(r["abstained"])),
        "token_f1": stat(ref, lambda r: r["token_f1"]),
        "reference_recall": stat(ref, lambda r: r["reference_recall"]),
    }


def main(path: str) -> None:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    out = summarise(payload["results"])
    Path(path).with_suffix(".ci.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    for key, value in out.items():
        if isinstance(value, dict) and value.get("n"):
            ci = value["ci95"]
            print(f"{key}: {value['mean']:.4f} ({ci[0]:.4f}-{ci[1]:.4f}) n={value['n']}")
        else:
            print(f"{key}: {value}")


if __name__ == "__main__":
    main(sys.argv[1])
