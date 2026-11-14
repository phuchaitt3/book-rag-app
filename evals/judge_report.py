"""Numbers for docs/benchmarks/judge.md from the collection and the judge's results (#244).

No human labels are used here. It reports the judge's score distribution on the whole sample and
on the 40 sheet rows, the mean score by system and by outcome (abstained or not, answerable or
not), and a sanity check that needs no labels: the Spearman correlation of the judge's score with
the token F1 of the answer against the reference answer (answerable questions only). That check is
NOT a validation: token overlap is a crude proxy.

  uv run python evals/judge_report.py
"""

from __future__ import annotations

import csv
import importlib.util
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from judge_agreement import spearman  # noqa: E402

ROOT = HERE.parent


def _answer_eval() -> Any:
    spec = importlib.util.spec_from_file_location("answer_eval_for_report", HERE / "answer_eval.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def distribution(scores: list[int]) -> dict[str, int]:
    count = Counter(scores)
    return {str(k): count.get(k, 0) for k in range(1, 6)}


def main() -> None:
    folder = ROOT / "experiments" / "judge"
    rows = json.loads((folder / "collection.json").read_text(encoding="utf-8"))["rows"]
    judged = {
        r["row_id"]: r["scores"][0]
        for r in json.loads((folder / "judge-results.json").read_text(encoding="utf-8"))["rows"]
    }
    with (folder / "labelling-key.csv").open(encoding="utf-8", newline="") as f:
        on_sheet = {r["row_id"] for r in csv.DictReader(f)}
    ae = _answer_eval()
    scored = [(r, judged[r["row_id"]]) for r in rows if judged[r["row_id"]] is not None]

    def mean(items: list[tuple[dict[str, Any], int]]) -> dict[str, Any]:
        return {"n": len(items), "mean": round(statistics.fmean(s for _, s in items), 2)}

    groups = {
        "answerable, answered": [
            x for x in scored if x[0]["kind"] != "unanswerable" and not x[0]["abstained"]
        ],
        "answerable, abstained (false abstain)": [
            x for x in scored if x[0]["kind"] != "unanswerable" and x[0]["abstained"]
        ],
        "unanswerable, abstained (correct)": [
            x for x in scored if x[0]["kind"] == "unanswerable" and x[0]["abstained"]
        ],
        "unanswerable, answered anyway": [
            x for x in scored if x[0]["kind"] == "unanswerable" and not x[0]["abstained"]
        ],
    }
    answered = groups["answerable, answered"]
    f1 = [ae.overlap(r["answer"], r["reference"])[0] for r, _ in answered]
    report = {
        "rows_scored": len(scored),
        "distribution_all": distribution([s for _, s in scored]),
        "distribution_sheet_rows": distribution([s for r, s in scored if r["row_id"] in on_sheet]),
        "sheet_rows_scored": sum(r["row_id"] in on_sheet for r, _ in scored),
        "mean_by_outcome": {k: mean(v) for k, v in groups.items() if v},
        "judge_vs_token_f1_spearman_answered": (
            round(rho, 3)
            if (rho := spearman([s for _, s in answered], [round(100 * x) for x in f1]))
            else None
        ),
        "judge_vs_token_f1_n": len(answered),
    }
    (folder / "judge-report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
