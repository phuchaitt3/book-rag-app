"""Agreement between the judge and the human labels, with bootstrap 95% intervals (#244).

Run when the human has filled in the `score` column of the labelling sheet and committed it:

  uv run python evals/judge_agreement.py

Compares the judge's `score` (first run, `judge-results.json`) with the human's 1-5 `score` row by
row (matched on `row_id`): quadratic-weighted Cohen's kappa, Spearman's rho (ties get the average
rank), exact agreement and agreement within one point. Intervals are bootstrap 95% (10,000
resamples of the rows, seed 244); a resample where a statistic is undefined (one rater gives the
same score to every row in it) is skipped and counted. With no human score at all the script stops:
the judge stays UNVALIDATED.

Environment: SHEET (experiments/judge/labelling-sheet.csv), JUDGE_RESULTS
(experiments/judge/judge-results.json), AGREEMENT_OUT (experiments/judge/agreement.json).
"""

from __future__ import annotations

import csv
import json
import math
import os
import random
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
LEVELS = (1, 2, 3, 4, 5)

Stat = Callable[[Sequence[int], Sequence[int]], float | None]


def weighted_kappa(
    a: Sequence[int], b: Sequence[int], levels: Sequence[int] = LEVELS
) -> float | None:
    """Quadratic-weighted Cohen's kappa; None when chance disagreement is zero (undefined)."""
    n = len(a)
    k = len(levels)
    index = {v: i for i, v in enumerate(levels)}
    observed = [[0.0] * k for _ in range(k)]
    for x, y in zip(a, b, strict=True):
        observed[index[x]][index[y]] += 1 / n
    row = [sum(r) for r in observed]
    col = [sum(observed[i][j] for i in range(k)) for j in range(k)]
    num = den = 0.0
    for i in range(k):
        for j in range(k):
            w = ((i - j) / (k - 1)) ** 2
            num += w * observed[i][j]
            den += w * row[i] * col[j]
    return None if den == 0 else 1 - num / den


def _ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for t in range(i, j + 1):
            ranks[order[t]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(a: Sequence[int], b: Sequence[int]) -> float | None:
    """Spearman's rho: Pearson correlation of the average ranks; None if a rater is constant."""
    ra, rb = _ranks(a), _ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb, strict=True))
    va, vb = sum((x - ma) ** 2 for x in ra), sum((y - mb) ** 2 for y in rb)
    if va == 0 or vb == 0:
        return None
    return cov / math.sqrt(va * vb)


def bootstrap_interval(
    a: Sequence[int], b: Sequence[int], stat: Stat, seed: int = 244, reps: int = 10_000
) -> tuple[list[float] | None, int]:
    """(95% interval of `stat` over resampled rows, number of undefined resamples skipped)."""
    rng = random.Random(seed)
    n = len(a)
    values: list[float] = []
    skipped = 0
    for _ in range(reps):
        idx = [rng.randrange(n) for _ in range(n)]
        value = stat([a[i] for i in idx], [b[i] for i in idx])
        if value is None:
            skipped += 1
        else:
            values.append(value)
    if len(values) < reps // 2:
        return None, skipped
    values.sort()
    lo, hi = values[int(0.025 * len(values))], values[int(0.975 * len(values))]
    return [round(lo, 3), round(hi, 3)], skipped


def agreement(judge: Sequence[int], human: Sequence[int]) -> dict[str, Any]:
    if len(judge) != len(human) or not judge:
        raise ValueError("need the same, non-zero number of judge and human scores")
    kappa, rho = weighted_kappa(judge, human), spearman(judge, human)
    kappa_ci, kappa_skipped = bootstrap_interval(judge, human, weighted_kappa)
    rho_ci, rho_skipped = bootstrap_interval(judge, human, spearman)
    n = len(judge)
    same = sum(x == y for x, y in zip(judge, human, strict=True))
    near = sum(abs(x - y) <= 1 for x, y in zip(judge, human, strict=True))
    return {
        "n": n,
        "weighted_kappa_quadratic": None if kappa is None else round(kappa, 3),
        "weighted_kappa_ci95": kappa_ci,
        "kappa_undefined_resamples": kappa_skipped,
        "spearman_rho": None if rho is None else round(rho, 3),
        "spearman_ci95": rho_ci,
        "spearman_undefined_resamples": rho_skipped,
        "exact_agreement_pct": round(100 * same / n, 1),
        "within_1_pct": round(100 * near / n, 1),
        "judge_mean": round(sum(judge) / n, 2),
        "human_mean": round(sum(human) / n, 2),
    }


def read_human_scores(path: Path) -> dict[str, int]:
    """Filled scores by row_id. A non-empty score that is not an integer 1-5 is an error."""
    scores: dict[str, int] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            raw = (row.get("score") or "").strip()
            if not raw:
                continue
            if not raw.isdigit() or not 1 <= int(raw) <= 5:
                raise ValueError(f"row {row['row_id']}: score {raw!r} is not an integer 1-5")
            scores[row["row_id"]] = int(raw)
    return scores


def compare(human: Mapping[str, int], judge_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Match on row_id. Rows the judge could not score are left out and counted."""
    judged = {r["row_id"]: r["scores"][0] for r in judge_rows}
    unmatched = sorted(set(human) - set(judged))
    if unmatched:
        raise ValueError(f"human scores for rows the judge never saw: {unmatched[:5]}")
    pairs = [(judged[k], v) for k, v in human.items() if judged[k] is not None]
    result = agreement([p[0] for p in pairs], [p[1] for p in pairs])
    result["labelled_rows"] = len(human)
    result["judge_unparsed_rows_left_out"] = len(human) - len(pairs)
    return result


def main() -> None:
    env = os.environ
    sheet = Path(env.get("SHEET", ROOT / "experiments" / "judge" / "labelling-sheet.csv"))
    results = Path(env.get("JUDGE_RESULTS", ROOT / "experiments" / "judge" / "judge-results.json"))
    out = Path(env.get("AGREEMENT_OUT", ROOT / "experiments" / "judge" / "agreement.json"))
    human = read_human_scores(sheet)
    if not human:
        raise SystemExit("the sheet has no human scores yet: the judge stays UNVALIDATED")
    result = compare(human, json.loads(results.read_text(encoding="utf-8"))["rows"])
    out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
