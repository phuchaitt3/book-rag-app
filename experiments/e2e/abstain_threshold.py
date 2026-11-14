"""Pick the abstain threshold on the seen questions and report it on the blind ones (#222).

Input: abstain-scores-<label>.json from abstain_scores.py (the best passage's score per question).
A question abstains when its top score is under the threshold. Per label (reranker off or on):

- the threshold is chosen on the seen split only: the highest score cut such that at most
  MAX_FALSE_ABSTAIN (default 5%) of the seen answerable questions would abstain;
- a trade-off table lists several cuts (the seen answerable questions' score quantiles), each with
  its abstain rate on the unanswerable questions and its false-abstain rate on the answerable
  ones, on the seen split (where it was chosen) and the blind split (not used to choose);
- intervals are bootstrap 95% (10,000 resamples of the questions, seed 222), the answerable
  and unanswerable questions resampled separately.

  uv run python experiments/e2e/abstain_threshold.py rerank no-rerank

Environment: OUT_DIR (experiments/e2e/results), MAX_FALSE_ABSTAIN (0.05).
"""

from __future__ import annotations

import json
import os
import random
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
OUT_DIR = Path(os.environ.get("OUT_DIR", HERE / "results"))
MAX_FALSE_ABSTAIN = float(os.environ.get("MAX_FALSE_ABSTAIN", "0.05"))
QUANTILES = (0.0, 0.02, 0.05, 0.10, 0.20)


def rate(scores: list[float], threshold: float) -> float:
    return sum(s < threshold for s in scores) / len(scores)


def interval(
    scores: list[float], threshold: float, seed: int = 222, reps: int = 10_000
) -> list[float]:
    rng = random.Random(seed)
    n = len(scores)
    flags = [s < threshold for s in scores]
    means = sorted(sum(flags[rng.randrange(n)] for _ in range(n)) / n for _ in range(reps))
    return [round(100 * means[int(0.025 * reps)], 1), round(100 * means[int(0.975 * reps)], 1)]


def pick_threshold(answerable_seen: list[float], max_false: float) -> float:
    """The highest cut with at most `max_false` of the answerable questions under it."""
    ordered = sorted(answerable_seen)
    allowed = int(max_false * len(ordered))  # questions that may fall under the cut
    # A cut just above ordered[allowed - 1] puts `allowed` questions under it; use the score of
    # the next question as the cut (strictly-less comparison keeps it out).
    return ordered[allowed]


def split_scores(rows: list[dict[str, Any]], split: str) -> tuple[list[float], list[float]]:
    got = [r for r in rows if r["split"] == split and r["top_score"] is not None]
    return (
        [r["top_score"] for r in got if r["answerable"]],
        [r["top_score"] for r in got if not r["answerable"]],
    )


def cell(scores: list[float], threshold: float) -> dict[str, Any]:
    return {
        "n": len(scores),
        "pct": round(100 * rate(scores, threshold), 1),
        "ci95": interval(scores, threshold),
    }


def analyse(label: str) -> dict[str, Any]:
    payload = json.loads((OUT_DIR / f"abstain-scores-{label}.json").read_text(encoding="utf-8"))
    rows = payload["results"]
    seen_ans, seen_un = split_scores(rows, "seen")
    blind_ans, blind_un = split_scores(rows, "blind")
    chosen = pick_threshold(seen_ans, MAX_FALSE_ABSTAIN)
    ordered = sorted(seen_ans)
    cuts = {q: ordered[int(q * len(ordered))] for q in QUANTILES}
    table = []
    for q, t in cuts.items():
        table.append(
            {
                "seen_answerable_quantile": q,
                "threshold": t,
                "seen": {"unanswerable": cell(seen_un, t), "answerable": cell(seen_ans, t)},
                "blind": {"unanswerable": cell(blind_un, t), "answerable": cell(blind_ans, t)},
            }
        )
    return {
        "label": label,
        "max_false_abstain_on_seen": MAX_FALSE_ABSTAIN,
        "chosen_threshold": chosen,
        "chosen": {
            "seen": {"unanswerable": cell(seen_un, chosen), "answerable": cell(seen_ans, chosen)},
            "blind": {
                "unanswerable": cell(blind_un, chosen),
                "answerable": cell(blind_ans, chosen),
            },
        },
        "table": table,
        "score_summary": {
            name: {"min": min(v), "median": sorted(v)[len(v) // 2], "max": max(v)}
            for name, v in (
                ("seen_answerable", seen_ans),
                ("seen_unanswerable", seen_un),
                ("blind_answerable", blind_ans),
                ("blind_unanswerable", blind_un),
            )
        },
    }


def fmt(c: dict[str, Any]) -> str:
    return f"{c['pct']}% ({c['ci95'][0]}-{c['ci95'][1]})"


def markdown(result: dict[str, Any]) -> str:
    lines = [
        f"### {result['label']}",
        "",
        "| Threshold | Seen: abstain on unanswerable | Seen: false abstain | "
        "Blind: abstain on unanswerable | Blind: false abstain |",
        "|---|---|---|---|---|",
    ]
    for row in result["table"]:
        t = row["threshold"]
        seen, blind = row["seen"], row["blind"]
        mark = " (chosen)" if t == result["chosen_threshold"] else ""
        lines.append(
            f"| {t:.6g}{mark} | {fmt(seen['unanswerable'])} | {fmt(seen['answerable'])} | "
            f"{fmt(blind['unanswerable'])} | {fmt(blind['answerable'])} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    labels = sys.argv[1:]
    if not labels:
        sys.exit("usage: abstain_threshold.py <label> [<label> ...]")
    out = []
    for label in labels:
        result = analyse(label)
        out.append(result)
        print(markdown(result))
    (OUT_DIR / f"abstain-threshold-max{round(100 * MAX_FALSE_ABSTAIN)}.json").write_text(
        json.dumps(out, indent=1), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
