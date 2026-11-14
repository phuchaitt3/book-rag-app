"""LLM-as-judge for answer quality on a local model, no paid API (#244, on the #221 harness).

One answer at a time (pointwise) is shown to the judge with its question, the passages the answer
cites and, when there is one, the reference answer. The judge replies with JSON:

  {"faithfulness": 1-5, "completeness": 1-5, "fluency": 1-5, "score": 1-5, "reason": "..."}

- faithfulness: every claim is supported by the passages (a refusal is faithful);
- completeness: the answer gives what the question asks (against the reference when there is one);
- fluency: natural, correct Vietnamese;
- score: the overall 1-5 verdict, the number compared with a human's 1-5 (`judge_agreement.py`).

Run at temperature 0 with a fixed seed through Ollama. A reply that is not valid JSON, or whose
`score` is not an integer from 1 to 5, is recorded as a parse failure with the raw text; it never
becomes a made-up score. Sub-scores are kept when valid and dropped (set to None) when not.

Caveats (details in docs/benchmarks/judge.md):

- Self-preference: when the judge model is the model that wrote the answers it tends to rate them
  higher. The judge model is always stated in the results; here it is `qwen2.5:3b-instruct`, the
  same model as the answerer.
- Position bias: pointwise scoring has no answer order to bias, but the order of the passages and
  the position of the rubric text still can; the rubric is fixed and the passages keep the app's
  rank order. Pairwise comparison, where position bias is strongest, is not used.
- A 3B model is a weak judge; the score is meaningless as a number until `judge_agreement.py` has
  compared it with human labels (until then: UNVALIDATED).

`judge` takes any backend with `async complete(messages) -> str`, so tests use a scripted one.

Run over a collection made by `evals/judge_collect.py` (judges each row twice, to measure the
judge's own repeat consistency):

  JUDGE_IN=experiments/judge/collection.json uv run python evals/answer_judge.py

Environment: OLLAMA_URL (http://localhost:11434), JUDGE_MODEL (qwen2.5:3b-instruct), JUDGE_IN,
JUDGE_OUT (experiments/judge/judge-results.json), REPEATS (2).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import statistics
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

ROOT = Path(__file__).resolve().parent.parent

RUBRIC = """Bạn là giám khảo chấm câu trả lời của một hệ thống hỏi đáp về một cuốn sách tiếng Việt.
Bạn được cho: câu hỏi, các đoạn sách mà câu trả lời trích dẫn (đánh số [1], [2], ...), đáp án \
tham chiếu (có thể không có) và câu trả lời cần chấm.

Chấm ba tiêu chí, mỗi tiêu chí từ 1 đến 5 (số nguyên):
- faithfulness (trung thực với đoạn trích): mọi điều câu trả lời khẳng định đều có trong các đoạn \
trích. 5 = hoàn toàn có căn cứ; 3 = một phần có căn cứ; 1 = bịa hoặc mâu thuẫn với đoạn trích. \
Câu trả lời "không tìm thấy trong sách" là trung thực.
- completeness (đầy đủ): câu trả lời nêu đúng và đủ điều câu hỏi cần, so với đáp án tham chiếu. \
5 = đúng và đủ; 3 = đúng nhưng thiếu ý chính; 1 = sai hoặc không trả lời. Khi đáp án tham chiếu \
nói sách không có câu trả lời, từ chối trả lời là đúng và đầy đủ (5), còn bịa ra câu trả lời là 1.
- fluency (tiếng Việt): câu văn tự nhiên, đúng ngữ pháp và chính tả. 5 = tự nhiên; 1 = khó hiểu.

Sau đó cho điểm tổng "score" từ 1 đến 5: câu trả lời tốt đến đâu đối với người đọc cần câu trả \
lời đúng, có căn cứ trong sách. Sai hoặc bịa thì không quá 2, dù văn trôi chảy.

Chỉ trả lời bằng một đối tượng JSON, không thêm chữ nào khác:
{"faithfulness": <1-5>, "completeness": <1-5>, "fluency": <1-5>, "score": <1-5>, \
"reason": "<một hoặc hai câu giải thích>"}"""

NO_REFERENCE = "(không có)"
NO_PASSAGES = "(không có đoạn trích nào)"


class JudgeBackend(Protocol):
    model: str

    async def complete(self, messages: Sequence[Mapping[str, str]]) -> str: ...


@dataclass(frozen=True)
class Verdict:
    """One judged answer. `score` is None when the reply could not be parsed."""

    score: int | None
    faithfulness: int | None
    completeness: int | None
    fluency: int | None
    reason: str
    raw: str
    error: str | None = None


def format_passages(passages: Sequence[Mapping[str, Any]]) -> str:
    if not passages:
        return NO_PASSAGES
    parts = []
    for p in passages:
        where = ", ".join(
            str(x) for x in (p.get("section"), f"tr. {p['page']}" if p.get("page") else None) if x
        )
        parts.append(f"[{p['number']}] ({where})\n{p['text']}")
    return "\n\n".join(parts)


def build_messages(
    question: str,
    passages: Sequence[Mapping[str, Any]],
    answer: str,
    reference: str | None = None,
) -> list[dict[str, str]]:
    user = (
        f"Câu hỏi: {question}\n\n"
        f"Các đoạn trích:\n{format_passages(passages)}\n\n"
        f"Đáp án tham chiếu: {reference or NO_REFERENCE}\n\n"
        f"Câu trả lời cần chấm:\n{answer}"
    )
    return [{"role": "system", "content": RUBRIC}, {"role": "user", "content": user}]


def _grade(value: object) -> int | None:
    """An integer 1-5 (a whole float such as 4.0 or a digit string is accepted), else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and re.fullmatch(r"\s*[1-5]\s*", value):
        value = int(value)
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return value if isinstance(value, int) and 1 <= value <= 5 else None


def parse_verdict(raw: str) -> Verdict:
    """Parse the judge's reply. Never raises: a bad reply gives `score=None` and an `error`."""
    text = raw.strip()
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    try:
        data = json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        try:
            data = json.loads(text[start : end + 1]) if 0 <= start < end else None
        except ValueError:
            data = None
    if not isinstance(data, dict):
        return Verdict(None, None, None, None, "", raw, "not a JSON object")
    score = _grade(data.get("score"))
    reason = data.get("reason")
    sub = {k: _grade(data.get(k)) for k in ("faithfulness", "completeness", "fluency")}
    return Verdict(
        score,
        sub["faithfulness"],
        sub["completeness"],
        sub["fluency"],
        reason.strip() if isinstance(reason, str) else "",
        raw,
        None if score is not None else f"score {data.get('score')!r} is not an integer 1-5",
    )


async def judge(
    backend: JudgeBackend,
    question: str,
    passages: Sequence[Mapping[str, Any]],
    answer: str,
    reference: str | None = None,
) -> tuple[Verdict, float]:
    """(verdict, seconds). A backend failure is a parse failure with the error, not a crash."""
    start = time.perf_counter()
    try:
        raw = await backend.complete(build_messages(question, passages, answer, reference))
    except httpx.HTTPError as exc:
        return Verdict(None, None, None, None, "", "", f"backend: {type(exc).__name__}"), (
            time.perf_counter() - start
        )
    return parse_verdict(raw), time.perf_counter() - start


class OllamaJudge:
    """Ollama's chat API at temperature 0, a fixed seed and JSON output."""

    def __init__(self, client: httpx.AsyncClient, model: str) -> None:
        self._client = client
        self.model = model

    async def complete(self, messages: Sequence[Mapping[str, str]]) -> str:
        response = await self._client.post(
            "/api/chat",
            json={
                "model": self.model,
                "messages": list(messages),
                "stream": False,
                "format": "json",
                "options": {"temperature": 0, "seed": 244, "num_ctx": 8192},
            },
        )
        response.raise_for_status()
        return str(response.json()["message"]["content"])


def repeat_consistency(runs: Sequence[Sequence[int | None]]) -> dict[str, Any]:
    """Agreement of repeated runs on the same inputs: `runs[r][i]` is run r's score for row i.

    Compares run 0 with every other run: the share of rows with the same score, and the share
    within one point. Rows where either score is missing are left out and counted.
    """
    pairs = [(a, b) for other in runs[1:] for a, b in zip(runs[0], other, strict=True)]
    valid = [(a, b) for a, b in pairs if a is not None and b is not None]
    if not valid:
        return {"pairs": len(pairs), "compared": 0, "identical_pct": None, "within_1_pct": None}
    return {
        "pairs": len(pairs),
        "compared": len(valid),
        "identical_pct": round(100 * sum(a == b for a, b in valid) / len(valid), 1),
        "within_1_pct": round(100 * sum(abs(a - b) <= 1 for a, b in valid) / len(valid), 1),
    }


def summarise(
    rows: Sequence[Mapping[str, Any]],
    runs: Sequence[Sequence[Verdict]],
    seconds: Sequence[Sequence[float]],
    *,
    model: str,
    answerer: str,
) -> dict[str, Any]:
    first = runs[0]
    scored = [v.score for v in first if v.score is not None]
    dist = {str(k): sum(s == k for s in scored) for k in range(1, 6)}
    by_kind: dict[str, dict[str, Any]] = {}
    for kind in sorted({str(r.get("system")) for r in rows}):
        got = [v.score for r, v in zip(rows, first, strict=True) if str(r.get("system")) == kind]
        ok = [s for s in got if s is not None]
        by_kind[kind] = {"n": len(got), "mean": round(statistics.fmean(ok), 2) if ok else None}
    return {
        "judge_model": model,
        "answer_model": answerer,
        "same_model_as_answerer": model == answerer,
        "validated_against_humans": False,
        "rows": len(rows),
        "repeats": len(runs),
        "parse_failures_run1": sum(v.score is None for v in first),
        "score_distribution_run1": dist,
        "score_mean_run1": round(statistics.fmean(scored), 3) if scored else None,
        "mean_score_by_system_run1": by_kind,
        "repeat_consistency": repeat_consistency([[v.score for v in run] for run in runs]),
        "latency_mean_s": round(statistics.fmean(s for run in seconds for s in run), 3),
        "latency_median_s": round(statistics.median(s for run in seconds for s in run), 3),
    }


async def judge_rows(
    backend: JudgeBackend, rows: Sequence[Mapping[str, Any]], repeats: int = 2
) -> tuple[list[list[Verdict]], list[list[float]]]:
    """Judge every row `repeats` times, one request at a time (one GPU, no batching effects)."""
    runs: list[list[Verdict]] = []
    seconds: list[list[float]] = []
    for _ in range(repeats):
        verdicts, times = [], []
        for r in rows:
            v, s = await judge(
                backend, r["question"], r["passages"], r["answer"], r.get("reference")
            )
            verdicts.append(v)
            times.append(s)
        runs.append(verdicts)
        seconds.append(times)
    return runs, seconds


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")


async def main() -> None:
    env = os.environ
    source = Path(env.get("JUDGE_IN", ROOT / "experiments" / "judge" / "collection.json"))
    out = Path(env.get("JUDGE_OUT", ROOT / "experiments" / "judge" / "judge-results.json"))
    collection = json.loads(source.read_text(encoding="utf-8"))  # noqa: ASYNC240
    rows = collection["rows"]
    model = env.get("JUDGE_MODEL", "qwen2.5:3b-instruct")
    async with httpx.AsyncClient(
        base_url=env.get("OLLAMA_URL", "http://localhost:11434"), timeout=300
    ) as client:
        runs, seconds = await judge_rows(
            OllamaJudge(client, model), rows, int(env.get("REPEATS", 2))
        )
    summary = summarise(rows, runs, seconds, model=model, answerer=collection["answer_model"])
    per_row = [
        {
            "row_id": r["row_id"],
            "scores": [run[i].score for run in runs],
            "verdict": {k: v for k, v in vars(runs[0][i]).items() if k != "raw"},
            "raw": [run[i].raw for run in runs],
            "seconds": [s[i] for s in seconds],
        }
        for i, r in enumerate(rows)
    ]
    write_json(out, {"summary": summary, "rows": per_row})
    print(json.dumps(summary, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
