# ruff: noqa: E501
"""Judge the answers of one arm with the #244 judge (exploratory; #287).

Reads `results/<LABEL>.json` written by `run_arm.py` and scores every answer once with
`evals/answer_judge.py` (temperature 0, seed 244, `qwen2.5:3b-instruct`: the same model as the 3B
answerer, so these scores are exploratory; the judge is not yet checked against humans, #251).
Writes `results/<LABEL>-judged.json`.

  LABEL=3b OLLAMA_URL=http://localhost:11434 uv run python experiments/qwen_size/judge_arm.py

Environment: LABEL (required), OLLAMA_URL, JUDGE_MODEL (qwen2.5:3b-instruct), OUT_DIR.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from run_arm import ROOT, load_module  # noqa: E402

aj = load_module("answer_judge_for_qwen_size", ROOT / "evals" / "answer_judge.py")
NO_ANSWER = "Sách không có câu trả lời cho câu hỏi này (câu hỏi ngoài phạm vi sách)."


async def main() -> None:
    env = os.environ
    label = env["LABEL"]
    out = Path(env.get("OUT_DIR", HERE / "results"))
    data = json.loads((out / f"{label}.json").read_text(encoding="utf-8"))
    results = [r for r in data["results"] if r["format_error"] is None and r["answer"].strip()]
    rows = [
        {
            "question": r["question"],
            "passages": r["passages"],
            "answer": r["answer"],
            "reference": r["reference"] or NO_ANSWER,
        }
        for r in results
    ]
    model = env.get("JUDGE_MODEL", "qwen2.5:3b-instruct")
    async with httpx.AsyncClient(
        base_url=env.get("OLLAMA_URL", "http://localhost:11434"), timeout=300
    ) as client:
        runs, seconds = await aj.judge_rows(aj.OllamaJudge(client, model), rows, repeats=1)
    judged: list[dict[str, Any]] = []
    for r, v, s in zip(results, runs[0], seconds[0], strict=True):
        judged.append(
            {
                "id": r["id"],
                "kind": r["kind"],
                "score": v.score,
                "faithfulness": v.faithfulness,
                "completeness": v.completeness,
                "fluency": v.fluency,
                "error": v.error,
                "seconds": round(s, 3),
            }
        )
    payload = {"label": label, "judge_model": model, "answer_model": data["meta"]["model"]}
    (out / f"{label}-judged.json").write_text(
        json.dumps({**payload, "rows": judged}, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    print(
        f"{label}: judged {len(judged)} answers, {sum(j['score'] is None for j in judged)} parse failures"
    )


if __name__ == "__main__":
    asyncio.run(main())
