# ruff: noqa: E501
"""Tables and the pre-registered verdict for the 0.5B vs 3B comparison (#287).

Reads `results/0.5b.json` and `results/3b.json` (and the `-judged.json` files when present) and
writes `results/report.md` and `results/summary.json`. The metrics, the "real difference" rule
and the verdict rule are those of docs/benchmarks/qwen-size-compare.md, "Fixed before the run".
Intervals are 95% bootstraps over questions (10,000 resamples, seed 287).

  uv run python experiments/qwen_size/report.py
"""

from __future__ import annotations

import json
import math
import os
import random
import re
import statistics
import unicodedata
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
OUT = Path(os.environ.get("OUT_DIR", HERE / "results"))
RESAMPLES, SEED = 10_000, 287
RATE_MARGIN, JUDGE_MARGIN, F1_MARGIN = 5.0, 0.5, 0.05

REFUSAL = re.compile(
    r"không (tìm thấy|có (thông tin|câu trả lời|đề cập|nói)|đề cập|nêu|rõ)"
    r"|không được (nêu|đề cập)"
    r"|(do(es)? not|no) (contain|seem|answer|information|passage)"
)

Interval = tuple[float, float]


def boot(values: Sequence[float], stat: Callable[[list[float]], float]) -> Interval:
    rng = random.Random(SEED)
    n = len(values)
    stats = sorted(stat([values[rng.randrange(n)] for _ in range(n)]) for _ in range(RESAMPLES))
    return stats[int(0.025 * RESAMPLES)], stats[int(0.975 * RESAMPLES) - 1]


def nearest_rank(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[max(1, math.ceil(p / 100 * len(ordered))) - 1]


def median(values: list[float]) -> float:
    return nearest_rank(values, 50)


def p90(values: list[float]) -> float:
    return nearest_rank(values, 90)


def load(label: str) -> dict[str, Any]:
    data = json.loads((OUT / f"{label}.json").read_text(encoding="utf-8"))
    path = OUT / f"{label}-judged.json"
    judged = json.loads(path.read_text(encoding="utf-8"))["rows"] if path.exists() else []
    data["judged"] = {j["id"]: j["score"] for j in judged if j["score"] is not None}
    data["by_id"] = {r["id"]: r for r in data["results"]}
    return data


def refuses(result: dict[str, Any]) -> bool:
    text = unicodedata.normalize("NFC", result["answer"]).lower()
    return bool(result["abstained"] or REFUSAL.search(text))


def metrics(arm: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Per-question value of each metric, keyed by question id (only questions it applies to)."""
    out: dict[str, dict[str, float]] = {
        k: {} for k in ("P", "S1", "S2", "S3", "J_blind", "J_unans")
    }
    for r in arm["results"]:
        if r["kind"] == "blind":
            out["P"][r["id"]] = float(bool(r.get("cited_answer_hit")))
            out["S3"][r["id"]] = float(r.get("token_f1", 0.0))
            if not r["abstained"] and r["format_error"] is None:
                out["S1"][r["id"]] = float(r.get("markers", 0) - r.get("invalid_markers", 0) > 0)
            if r["id"] in arm["judged"]:
                out["J_blind"][r["id"]] = float(arm["judged"][r["id"]])
        else:
            out["S2"][r["id"]] = float(refuses(r))
            if r["id"] in arm["judged"]:
                out["J_unans"][r["id"]] = float(arm["judged"][r["id"]])
    return out


def paired(a: dict[str, float], b: dict[str, float]) -> list[float]:
    return [a[k] - b[k] for k in a if k in b]


def mean(values: Sequence[float]) -> float:
    return statistics.fmean(values)


NAMES = {
    "P": ("Cited-answer hit % (primary, 208 blind)", 100.0, RATE_MARGIN),
    "S1": ("Cites a retrieved passage % (blind, not abstained)", 100.0, RATE_MARGIN),
    "S2": ("Correct abstention % (40 unanswerable)", 100.0, RATE_MARGIN),
    "S3": ("Token F1, mean (208 blind)", 1.0, F1_MARGIN),
    "J_blind": ("Judge score, mean 1-5, blind (exploratory)", 1.0, JUDGE_MARGIN),
    "J_unans": ("Judge score, mean 1-5, unanswerable (exploratory)", 1.0, JUDGE_MARGIN),
}


def compare(
    m_small: dict[str, dict[str, float]], m_big: dict[str, dict[str, float]]
) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for key, (name, scale, margin) in NAMES.items():
        small, big = m_small[key], m_big[key]
        if not small or not big:
            continue
        diffs = paired(big, small)
        if not diffs:
            continue
        lo, hi = boot(diffs, mean)
        rows[key] = {
            "name": name,
            "n_small": len(small),
            "n_big": len(big),
            "n_paired": len(diffs),
            "small": round(scale * mean(list(small.values())), 3),
            "small_ci": [round(scale * x, 3) for x in boot(list(small.values()), mean)],
            "big": round(scale * mean(list(big.values())), 3),
            "big_ci": [round(scale * x, 3) for x in boot(list(big.values()), mean)],
            "diff": round(scale * mean(diffs), 3),
            "diff_ci": [round(scale * lo, 3), round(scale * hi, 3)],
            "margin": margin,
            "real": lo > 0 or hi < 0,
        }
    return rows


def verdict(rows: dict[str, Any]) -> tuple[str, str]:
    """The pre-registered rule, applied to P, S1, S2 and S3 only."""
    p = rows["P"]
    lo, hi = p["diff_ci"]
    if lo > 0:
        return (
            "3B",
            "The interval of the primary difference (3B minus 0.5B) excludes zero in favour of 3B.",
        )
    secondary_for_3b = [
        k
        for k in ("S1", "S2", "S3")
        if k in rows and rows[k]["diff_ci"][0] > 0 and rows[k]["diff"] >= rows[k]["margin"]
    ]
    if lo > -RATE_MARGIN and hi < RATE_MARGIN and not secondary_for_3b:
        return (
            "0.5B",
            "The primary interval lies inside +-5 points and no secondary metric shows a meaningful, real advantage for 3B.",
        )
    reason = "The primary interval is wider than +-5 points or excludes zero in favour of 0.5B"
    if secondary_for_3b:
        reason = "A secondary metric favours 3B meaningfully (" + ", ".join(secondary_for_3b) + ")"
    return "cannot tell / mixed", reason + "."


def cost(arm: dict[str, Any]) -> dict[str, Any]:
    ok = [r for r in arm["results"] if r["ttft_s"] is not None]
    ttft = [r["ttft_s"] for r in ok]
    total = [r["total_s"] for r in arm["results"] if r["format_error"] is None]
    return {
        "n_ttft": len(ttft),
        "ttft_median": round(median(ttft), 2),
        "ttft_median_ci": [round(x, 2) for x in boot(ttft, median)],
        "ttft_p90": round(p90(ttft), 2),
        "ttft_p90_ci": [round(x, 2) for x in boot(ttft, p90)],
        "total_median": round(median(total), 2),
        "total_median_ci": [round(x, 2) for x in boot(total, median)],
        "total_p90": round(p90(total), 2),
        "vram": arm["meta"]["vram"],
        "errors": [arm["meta"]["format_errors"], arm["meta"]["stream_errors"]],
    }


def fmt(value: float, ci: Sequence[float], digits: int = 1) -> str:
    return f"{value:.{digits}f} ({ci[0]:.{digits}f} to {ci[1]:.{digits}f})"


def render(
    rows: dict[str, Any], costs: dict[str, Any], decision: tuple[str, str], meta: dict[str, Any]
) -> str:
    lines = [
        "| Metric | 0.5B | 3B | 3B minus 0.5B | Real? |",
        "|---|---|---|---|---|",
    ]
    for r in rows.values():
        d = 2 if r["margin"] < 1 else 1
        lines.append(
            f"| {r['name']} | {fmt(r['small'], r['small_ci'], d)} | {fmt(r['big'], r['big_ci'], d)} "
            f"| {r['diff']:+.{d}f} ({r['diff_ci'][0]:+.{d}f} to {r['diff_ci'][1]:+.{d}f}) "
            f"| {'yes' if r['real'] else 'no'}, {'meaningful' if r['real'] and abs(r['diff']) >= r['margin'] else 'not meaningful'} |"
        )
    c1, c2 = costs["0.5b"], costs["3b"]
    lines += [
        "",
        "| Cost | 0.5B | 3B |",
        "|---|---|---|",
        f"| Time to first token, median s | {fmt(c1['ttft_median'], c1['ttft_median_ci'], 2)} | {fmt(c2['ttft_median'], c2['ttft_median_ci'], 2)} |",
        f"| Time to first token, p90 s | {fmt(c1['ttft_p90'], c1['ttft_p90_ci'], 2)} | {fmt(c2['ttft_p90'], c2['ttft_p90_ci'], 2)} |",
        f"| Whole answer, median s | {fmt(c1['total_median'], c1['total_median_ci'], 2)} | {fmt(c2['total_median'], c2['total_median_ci'], 2)} |",
        f"| Whole answer, p90 s | {c1['total_p90']:.2f} | {c2['total_p90']:.2f} |",
        f"| Peak GPU memory MiB (all processes; idle before the arm) | {c1['vram']['peak_mib']} ({c1['vram']['baseline_mib']}) | {c2['vram']['peak_mib']} ({c2['vram']['baseline_mib']}) |",
        f"| Format errors / stream errors | {c1['errors'][0]} / {c1['errors'][1]} | {c2['errors'][0]} / {c2['errors'][1]} |",
        "",
        f"Verdict by the pre-registered rule: **{decision[0]}**. {decision[1]}",
        f"Commit {meta['commit']}; arms ran {meta['0.5b_start']} and {meta['3b_start']}.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    small, big = load("0.5b"), load("3b")
    rows = compare(metrics(small), metrics(big))
    costs = {"0.5b": cost(small), "3b": cost(big)}
    decision = verdict(rows)
    meta = {
        "commit": big["meta"]["commit"],
        "0.5b_start": small["meta"]["started"],
        "3b_start": big["meta"]["started"],
    }
    summary = {"metrics": rows, "cost": costs, "verdict": decision, "meta": meta}
    (OUT / "summary.json").write_text(
        json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    text = render(rows, costs, decision, meta)
    (OUT / "report.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
