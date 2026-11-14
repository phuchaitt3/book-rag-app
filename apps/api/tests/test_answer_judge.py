"""The judge (#244): reply parsing, a scripted backend, the sheet and the agreement script.

No model and no network: the judge backend is a scripted fake, and the agreement script runs on
synthetic labels.
"""

import csv
import importlib.util
import json
import random
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[3]


def load(name: str) -> ModuleType:
    sys.path.insert(0, str(ROOT / "evals"))  # judge_sheet imports answer_judge by name
    spec = importlib.util.spec_from_file_location(
        f"{name}_under_test", ROOT / "evals" / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def aj() -> ModuleType:
    return load("answer_judge")


@pytest.fixture(scope="module")
def ag() -> ModuleType:
    return load("judge_agreement")


@pytest.fixture(scope="module")
def sheet() -> ModuleType:
    return load("judge_sheet")


GOOD = '{"faithfulness": 5, "completeness": 4, "fluency": 5, "score": 4, "reason": "Đúng."}'


class Scripted:
    model = "fake-judge"

    def __init__(self, replies: Sequence[str | Exception]) -> None:
        self._replies = list(replies)
        self.calls: list[Sequence[Mapping[str, str]]] = []

    async def complete(self, messages: Sequence[Mapping[str, str]]) -> str:
        self.calls.append(messages)
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def test_parse_valid(aj: ModuleType) -> None:
    v = aj.parse_verdict(GOOD)
    assert (v.score, v.faithfulness, v.completeness, v.fluency) == (4, 5, 4, 5)
    assert v.reason == "Đúng." and v.error is None


def test_parse_fenced_and_surrounded_json(aj: ModuleType) -> None:
    assert aj.parse_verdict(f"```json\n{GOOD}\n```").score == 4
    assert aj.parse_verdict(f"Kết quả: {GOOD} Hết.").score == 4


@pytest.mark.parametrize("bad", ["", "not json at all", "[1, 2]", '{"score": ', "null"])
def test_parse_malformed_is_a_failure_not_a_score(aj: ModuleType, bad: str) -> None:
    v = aj.parse_verdict(bad)
    assert v.score is None and v.error is not None and v.raw == bad


@pytest.mark.parametrize("score", [0, 6, -1, 3.5, "five", None, True, [4], "4.5"])
def test_parse_out_of_range_score(aj: ModuleType, score: object) -> None:
    v = aj.parse_verdict(json.dumps({"score": score, "reason": "x"}))
    assert v.score is None and "not an integer 1-5" in (v.error or "")


def test_parse_accepts_whole_number_forms(aj: ModuleType) -> None:
    assert aj.parse_verdict('{"score": 4.0}').score == 4
    assert aj.parse_verdict('{"score": "3"}').score == 3


def test_bad_subscore_is_dropped_but_valid_score_kept(aj: ModuleType) -> None:
    v = aj.parse_verdict('{"faithfulness": 9, "completeness": 3, "fluency": "x", "score": 2}')
    assert (v.score, v.faithfulness, v.completeness, v.fluency) == (2, None, 3, None)


def test_prompt_has_question_passages_reference_and_answer_only(aj: ModuleType) -> None:
    passages = [{"number": 2, "section": "Quyển I", "page": 7, "text": "Văn bản đoạn."}]
    system, user = aj.build_messages("Hỏi gì?", passages, "Trả lời [2]", "Đáp án")
    assert system["role"] == "system" and "1 đến 5" in system["content"]
    for part in ("Hỏi gì?", "[2] (Quyển I, tr. 7)", "Văn bản đoạn.", "Đáp án", "Trả lời [2]"):
        assert part in user["content"]
    none = aj.build_messages("q", [], "a")[1]["content"]
    assert aj.NO_PASSAGES in none and aj.NO_REFERENCE in none


async def test_judge_with_scripted_backend(aj: ModuleType) -> None:
    backend = Scripted([GOOD, "garbage", httpx.ConnectError("down")])
    ok, seconds = await aj.judge(backend, "q", [], "a")
    assert ok.score == 4 and seconds >= 0
    bad, _ = await aj.judge(backend, "q", [], "a")
    assert bad.score is None
    down, _ = await aj.judge(backend, "q", [], "a")
    assert down.score is None and down.error == "backend: ConnectError"


async def test_judge_rows_summary_and_repeat_consistency(aj: ModuleType) -> None:
    rows = [
        {"row_id": f"r{i}", "question": "q", "passages": [], "answer": "a", "system": s}
        for i, s in enumerate(["topk6", "topk6", "topk1"])
    ]

    def reply(score: object) -> str:
        return json.dumps({"score": score, "reason": "r"})

    # run 1: 5, 3, bad; run 2: 5, 4, 2
    backend = Scripted([reply(5), reply(3), reply(9), reply(5), reply(4), reply(2)])
    runs, seconds = await aj.judge_rows(backend, rows, repeats=2)
    s = aj.summarise(rows, runs, seconds, model="m", answerer="m")
    assert s["same_model_as_answerer"] is True and s["validated_against_humans"] is False
    assert s["parse_failures_run1"] == 1
    assert s["score_distribution_run1"] == {"1": 0, "2": 0, "3": 1, "4": 0, "5": 1}
    assert s["mean_score_by_system_run1"]["topk6"] == {"n": 2, "mean": 4.0}
    assert s["mean_score_by_system_run1"]["topk1"] == {"n": 1, "mean": None}
    # rows 0 and 1 compared (row 2 has a missing score): 1 of 2 identical, both within 1
    assert s["repeat_consistency"] == {
        "pairs": 3,
        "compared": 2,
        "identical_pct": 50.0,
        "within_1_pct": 100.0,
    }


def test_sheet_hides_the_system_and_leaves_scores_empty(sheet: ModuleType, tmp_path: Path) -> None:
    rows = [
        {
            "row_id": f"r{i:03d}",
            "qid": f"q{i}",
            "kind": "unanswerable" if i % 5 == 0 else "blind",
            "system": "topk1" if i % 2 else "topk6",
            "abstained": False,
            "question": f"Câu hỏi {i}?",
            "reference": "Đáp án",
            "answer": f"Trả lời {i}",
            "passages": [{"number": 1, "section": "S", "page": 3, "text": "Đoạn."}],
        }
        for i in range(1, 101)
    ]
    plan = (("topk6", "answerable", 3), ("topk1", "answerable", 2), ("topk6", "unanswerable", 1))
    chosen = sheet.select_rows(rows, plan, seed=1)
    assert len(chosen) == 6 and len({r["row_id"] for r in chosen}) == 6
    assert [r["row_id"] for r in chosen] == [
        r["row_id"] for r in sheet.select_rows(rows, plan, seed=1)
    ]
    sheet.write_sheet(tmp_path / "s.csv", chosen)
    sheet.write_key(tmp_path / "k.csv", chosen)
    with (tmp_path / "s.csv").open(encoding="utf-8-sig", newline="") as f:
        out = list(csv.DictReader(f))
    assert list(out[0]) == list(sheet.SHEET_COLUMNS)
    assert all(r["score"] == "" and r["note"] == "" for r in out)
    text = (tmp_path / "s.csv").read_text(encoding="utf-8-sig")
    assert "topk" not in text and "system" not in text
    key = list(csv.DictReader((tmp_path / "k.csv").open(encoding="utf-8")))
    assert {r["system"] for r in key} <= {"topk1", "topk6"}
    with pytest.raises(ValueError, match="need"):
        sheet.select_rows(rows, (("topk6", "unanswerable", 50),), seed=1)


def test_kappa_and_spearman_known_values(ag: ModuleType) -> None:
    a = [1, 2, 3, 4, 5, 3, 2, 4]
    assert ag.weighted_kappa(a, a) == pytest.approx(1.0)
    assert ag.spearman(a, a) == pytest.approx(1.0)
    assert ag.spearman([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]) == pytest.approx(-1.0)
    # both raters constant: kappa is undefined; one rater constant: kappa is 0, rho is undefined
    assert ag.weighted_kappa([3, 3, 3, 3], [3, 3, 3, 3]) is None
    assert ag.weighted_kappa([3, 3, 3, 3], [1, 2, 3, 4]) == pytest.approx(0.0)
    assert ag.spearman([3, 3, 3, 3], [1, 2, 3, 4]) is None
    # ties get the average rank: this is a textbook value
    assert ag.spearman([1, 2, 2, 4], [1, 3, 2, 4]) == pytest.approx(0.9487, abs=1e-3)
    # a worked quadratic-weighted kappa: perfect disagreement at the extremes is -1
    assert ag.weighted_kappa([1, 5, 1, 5], [5, 1, 5, 1]) == pytest.approx(-1.0)


def test_agreement_on_synthetic_labels(ag: ModuleType) -> None:
    human = [1, 2, 3, 4, 5] * 8
    judge = [
        min(5, max(1, h + d)) for h, d in zip(human, [0, 1, 0, -1, 0, 0, 0, 1] * 5, strict=True)
    ]
    result = ag.agreement(judge, human)
    assert result["n"] == 40
    assert result["weighted_kappa_quadratic"] > 0.8 and result["spearman_rho"] > 0.8
    lo, hi = result["weighted_kappa_ci95"]
    assert lo <= result["weighted_kappa_quadratic"] <= hi
    assert result["within_1_pct"] == 100.0 and 0 < result["exact_agreement_pct"] < 100
    # an independent judge: agreement near zero, interval covers zero
    shuffled = random.Random(5).sample(human, len(human))
    noise = ag.agreement(shuffled, human)
    assert noise["weighted_kappa_ci95"][0] < 0 < noise["weighted_kappa_ci95"][1]
    assert abs(noise["spearman_rho"]) < 0.5


def test_agreement_rejects_unequal_or_empty(ag: ModuleType) -> None:
    with pytest.raises(ValueError):
        ag.agreement([1, 2], [1])
    with pytest.raises(ValueError):
        ag.agreement([], [])


def test_read_human_scores_and_compare(ag: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "sheet.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["row_id", "score", "note"])
        w.writeheader()
        w.writerows(
            [
                {"row_id": "r1", "score": "5", "note": ""},
                {"row_id": "r2", "score": " 2 ", "note": "x"},
                {"row_id": "r3", "score": "", "note": ""},
                {"row_id": "r4", "score": "4", "note": ""},
                {"row_id": "r5", "score": "1", "note": ""},
            ]
        )
    human = ag.read_human_scores(path)
    assert human == {"r1": 5, "r2": 2, "r4": 4, "r5": 1}
    judged = [
        {"row_id": f"r{i}", "scores": [s, s]}
        for i, s in [(1, 5), (2, 3), (3, 3), (4, None), (5, 1)]
    ]
    result = ag.compare(human, judged)
    assert result["n"] == 3 and result["judge_unparsed_rows_left_out"] == 1
    assert result["labelled_rows"] == 4
    with pytest.raises(ValueError, match="never saw"):
        ag.compare({"r9": 3}, judged)
    path.write_text("row_id,score\nr1,7\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not an integer 1-5"):
        ag.read_human_scores(path)


def test_agreement_script_stops_on_an_unfilled_sheet(
    ag: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sheet_path = tmp_path / "sheet.csv"
    sheet_path.write_text("row_id,score\nr1,\nr2,\n", encoding="utf-8")
    results = tmp_path / "judge.json"
    results.write_text(json.dumps({"rows": []}), encoding="utf-8")
    monkeypatch.setenv("SHEET", str(sheet_path))
    monkeypatch.setenv("JUDGE_RESULTS", str(results))
    with pytest.raises(SystemExit, match="UNVALIDATED"):
        ag.main()
