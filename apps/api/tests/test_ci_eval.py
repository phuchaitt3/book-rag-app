"""The CI eval gate (#22): passes at the baseline, fails on a drop, a rise of an error count, a
changed sample size or a missing metric. Pure logic, no database."""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def ce() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "ci_eval_under_test", ROOT / "evals" / "ci_eval.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def baseline_scores(baseline: dict) -> dict:  # type: ignore[type-arg]
    """Scores equal to the baseline values, with each metric's sample size."""
    scores = {name: spec["value"] for name, spec in baseline["metrics"].items()}
    for spec in baseline["metrics"].values():
        scores[spec["n_key"]] = spec["n"]
    return scores


@pytest.fixture
def baseline() -> dict:  # type: ignore[type-arg]
    return json.loads((ROOT / "evals" / "baseline.json").read_text(encoding="utf-8"))


def test_passes_at_baseline(ce: ModuleType, baseline: dict) -> None:  # type: ignore[type-arg]
    rows = ce.compare(baseline_scores(baseline), baseline)
    assert rows and all(r["ok"] for r in rows)


def test_within_tolerance_and_better_pass(ce: ModuleType, baseline: dict) -> None:  # type: ignore[type-arg]
    scores = baseline_scores(baseline)
    scores["token_f1_mean"] -= baseline["metrics"]["token_f1_mean"]["tolerance"]
    scores["citation_hit_pct"] = 100.0
    scores["format_errors"] = 0
    assert all(r["ok"] for r in ce.compare(scores, baseline))


def test_drop_fails(ce: ModuleType, baseline: dict) -> None:  # type: ignore[type-arg]
    scores = baseline_scores(baseline)
    scores["citation_hit_pct"] = baseline["metrics"]["citation_hit_pct"]["value"] - 10
    failed = [r["metric"] for r in ce.compare(scores, baseline) if not r["ok"]]
    assert failed == ["citation_hit_pct"]


def test_rise_of_a_lower_is_better_metric_fails(ce: ModuleType, baseline: dict) -> None:  # type: ignore[type-arg]
    scores = baseline_scores(baseline)
    scores["format_errors"] = 1
    failed = [r["metric"] for r in ce.compare(scores, baseline) if not r["ok"]]
    assert failed == ["format_errors"]


def test_changed_n_or_missing_metric_fails(ce: ModuleType, baseline: dict) -> None:  # type: ignore[type-arg]
    scores = baseline_scores(baseline)
    scores["scored_for_hit"] += 1
    del scores["token_f1_mean"]
    failed = {r["metric"] for r in ce.compare(scores, baseline) if not r["ok"]}
    assert failed == {"citation_hit_pct", "cited_answer_hit_pct", "token_f1_mean"}


def test_main_exit_code_and_step_summary(
    ce: ModuleType,
    baseline: dict,  # type: ignore[type-arg]
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    scores = baseline_scores(baseline)
    ok_path = tmp_path / "ok.json"
    ok_path.write_text(json.dumps(scores), encoding="utf-8")
    assert ce.main([str(ok_path)]) == 0
    scores["token_f1_mean"] = 0.0
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps(scores), encoding="utf-8")
    assert ce.main([str(bad_path)]) == 1
    assert "FAIL" in summary.read_text(encoding="utf-8")
