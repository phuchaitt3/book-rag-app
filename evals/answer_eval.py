"""Answer-quality eval with deterministic metrics and no judge model (#221, for #22).

Each question of the book test set goes through the app's own `POST /books/{id}/chat` endpoint.
The reply is parsed as the server-sent events the API documents (`citations`, `token`*, then
`done` or `error`) and scored:

- citation hit: a returned citation's chunk contains the question's evidence sentence (the
  matching rule of `experiments/e2e/retrieval_check.py`, imported, not copied);
- cited-answer hit: the same, but only for chunks the answer cites with a `[n]` marker;
- citation validity: every `[n]` marker in the answer names a returned citation;
- answer overlap: token F1 and reference recall between the answer and the test set's
  reference answer (answerable questions only);
- format errors (not a valid stream, no `done`, empty answer, non-200) and stream errors (an
  `error` event).

`run_eval` takes any httpx client, so tests drive the ASGI app in memory with the fake providers
and a live run points it at the running API. Live run:

  BOOK_ID=<uuid> LABEL=ollama uv run python evals/answer_eval.py

Environment: API_URL (http://localhost:8000), DATABASE_URL
(postgresql://bookrag:bookrag@localhost:5432/bookrag), QUESTIONS (the committed set), KINDS
(blind), TOP_K (6), LIMIT (0 = all), LABEL (run), OUT_DIR (evals/results).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import statistics
import sys
import time
import unicodedata
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MARKER = re.compile(r"\[(\d+)\]")
_WORD = re.compile(r"\w+", re.UNICODE)


def _load_retrieval_check() -> ModuleType:
    """The retrieval scorer lives in a script that reads BOOK_ID when imported; load it by path."""
    path = ROOT / "experiments" / "e2e" / "retrieval_check.py"
    previous = os.environ.get("BOOK_ID")
    os.environ.setdefault("BOOK_ID", "00000000-0000-0000-0000-000000000000")
    try:
        spec = importlib.util.spec_from_file_location("retrieval_check_for_answer_eval", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            os.environ.pop("BOOK_ID", None)
    return module


norm: Callable[[str], str] = _load_retrieval_check().norm


def parse_events(text: str) -> list[tuple[str, Any]]:
    """Events of an SSE body as (name, json data). Raises ValueError on a malformed block."""
    events: list[tuple[str, Any]] = []
    for block in text.strip().split("\n\n"):
        if not block:
            continue
        lines = block.split("\n")
        if (
            len(lines) != 2
            or not lines[0].startswith("event: ")
            or not lines[1].startswith("data: ")
        ):
            raise ValueError(f"malformed event block: {block[:80]!r}")
        events.append((lines[0][7:], json.loads(lines[1][6:])))  # JSONDecodeError is a ValueError
    return events


def tokens(text: str) -> list[str]:
    """Lowercase NFC words; the `[n]` markers are removed first."""
    return _WORD.findall(unicodedata.normalize("NFC", MARKER.sub(" ", text)).lower())


def overlap(answer: str, reference: str) -> tuple[float, float]:
    """(token F1, reference recall) of `answer` against `reference`, counting repeated words."""
    got, want = Counter(tokens(answer)), Counter(tokens(reference))
    common = sum((got & want).values())
    if not common:
        return 0.0, 0.0
    precision, recall = common / sum(got.values()), common / sum(want.values())
    return 2 * precision * recall / (precision + recall), recall


def _stream_problem(names: list[str], answer: str) -> str | None:
    if "error" in names:
        return None  # a stream error is counted on its own, not as a format error
    if names.count("done") != 1 or names[-1] != "done":
        return "stream does not end with exactly one done"
    if set(names[1:-1]) - {"token"}:
        return f"unexpected events {sorted(set(names[1:-1]) - {'token'})}"
    if not answer.strip():
        return "empty answer"
    return None


def score_stream(
    status: int, body: str, row: Mapping[str, Any], texts: Mapping[str, str]
) -> dict[str, Any]:
    """Score one reply. `texts` maps a chunk id to its normalised text."""
    result: dict[str, Any] = {
        "id": row["id"],
        "status": status,
        "format_error": None,
        "stream_error": False,
        "answer": "",
        "citations": 0,
    }
    if status != 200:
        result["format_error"] = f"status {status}"
        return result
    try:
        events = parse_events(body)
    except ValueError as exc:
        result["format_error"] = str(exc)
        return result
    names = [name for name, _ in events]
    answer = "".join(d.get("text", "") for n, d in events if n == "token")
    result["answer"] = answer
    result["stream_error"] = "error" in names
    cites = events[0][1] if names[:1] == ["citations"] else None
    if not isinstance(cites, list):
        result["format_error"] = "first event is not citations"
        return result
    result["format_error"] = _stream_problem(names, answer)
    result["citations"] = len(cites)
    numbers = [int(m) for m in MARKER.findall(answer)]
    invalid = [n for n in numbers if not 1 <= n <= len(cites)]
    result.update(markers=len(numbers), invalid_markers=len(invalid), citation_valid=not invalid)
    if row.get("evidence"):
        evidence = norm(row["evidence"])
        ids = [c["chunk_id"] for c in cites]
        result["citation_rank"] = next(
            (i + 1 for i, cid in enumerate(ids) if evidence in texts.get(cid, "")), None
        )
        cited = {n for n in numbers if 1 <= n <= len(cites)}
        result["cited_answer_hit"] = any(evidence in texts.get(ids[n - 1], "") for n in cited)
    if row.get("answer"):
        f1, recall = overlap(answer, row["answer"])
        result.update(token_f1=round(f1, 4), reference_recall=round(recall, 4))
    return result


def _pct(values: Sequence[bool | int]) -> float | None:
    return round(100 * sum(values) / len(values), 1) if values else None


def _mean(results: list[dict[str, Any]], key: str) -> float | None:
    return round(statistics.fmean(r[key] for r in results), 4) if results else None


def summarise(results: list[dict[str, Any]], **meta: Any) -> dict[str, Any]:
    streamed = [r for r in results if "citation_valid" in r]
    with_evidence = [r for r in results if "citation_rank" in r]
    with_ref = [r for r in results if "token_f1" in r]
    return {
        **meta,
        "questions": len(results),
        "format_errors": sum(r["format_error"] is not None for r in results),
        "stream_errors": sum(r["stream_error"] for r in results),
        "scored_for_hit": len(with_evidence),
        "citation_hit_pct": _pct([r["citation_rank"] is not None for r in with_evidence]),
        "cited_answer_hit_pct": _pct([r["cited_answer_hit"] for r in with_evidence]),
        "citation_valid_pct": _pct([r["citation_valid"] for r in streamed]),
        "answers_without_marker_pct": _pct([r["markers"] == 0 for r in streamed]),
        "scored_for_overlap": len(with_ref),
        "token_f1_mean": _mean(with_ref, "token_f1"),
        "reference_recall_mean": _mean(with_ref, "reference_recall"),
    }


def markdown(summary: Mapping[str, Any]) -> str:
    rows = [
        ("Questions sent", summary["questions"]),
        ("Format errors", summary["format_errors"]),
        ("Stream errors (`error` event)", summary["stream_errors"]),
        (f"Citation hit % (n={summary['scored_for_hit']})", summary["citation_hit_pct"]),
        ("Cited-answer hit %", summary["cited_answer_hit_pct"]),
        ("Citation validity %", summary["citation_valid_pct"]),
        ("Answers with no `[n]` marker %", summary["answers_without_marker_pct"]),
        (f"Token F1, mean (n={summary['scored_for_overlap']})", summary["token_f1_mean"]),
        ("Reference recall, mean", summary["reference_recall_mean"]),
    ]
    head = f"# Answer eval: {summary.get('label', 'run')}\n\n| Metric | Value |\n|---|---|\n"
    return head + "".join(f"| {k} | {v} |\n" for k, v in rows)


def load_questions(path: Path, kinds: Sequence[str], limit: int = 0) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    rows = [r for r in (json.loads(x) for x in lines if x) if r["kind"] in kinds]
    return rows[:limit] if limit else rows


async def run_eval(
    client: httpx.AsyncClient,
    book_id: str,
    rows: Sequence[Mapping[str, Any]],
    texts: Mapping[str, str],
    *,
    top_k: int = 6,
    concurrency: int = 1,
) -> list[dict[str, Any]]:
    """Ask every question once. A transport failure counts as a format error, not a crash."""
    gate = asyncio.Semaphore(concurrency)

    async def one(row: Mapping[str, Any]) -> dict[str, Any]:
        async with gate:
            start = time.perf_counter()
            try:
                response = await client.post(
                    f"/books/{book_id}/chat", json={"question": row["question"], "top_k": top_k}
                )
                result = score_stream(response.status_code, response.text, row, texts)
            except httpx.HTTPError as exc:
                result = score_stream(0, "", row, texts)
                result["format_error"] = f"transport: {type(exc).__name__}"
            result["total_s"] = round(time.perf_counter() - start, 3)
            return result

    return list(await asyncio.gather(*(one(r) for r in rows)))


def write_report(
    out_dir: Path, label: str, summary: dict[str, Any], results: list[dict[str, Any]]
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {"summary": summary, "results": results}
    (out_dir / f"answer-eval-{label}.json").write_text(
        json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    (out_dir / f"answer-eval-{label}.md").write_text(markdown(summary), encoding="utf-8")


async def chunk_texts(database_url: str, book_id: str) -> dict[str, str]:
    import asyncpg  # type: ignore[import-untyped]

    conn = await asyncpg.connect(database_url)
    try:
        rows = await conn.fetch("SELECT id, text FROM chunks WHERE book_id = $1::uuid", book_id)
    finally:
        await conn.close()
    return {str(r["id"]): norm(r["text"]) for r in rows}


async def main() -> None:
    env = os.environ
    book_id = env["BOOK_ID"]
    label = env.get("LABEL", "run")
    default_set = ROOT / "experiments" / "book-testset" / "questions.jsonl"
    rows = load_questions(
        Path(env.get("QUESTIONS", default_set)),
        env.get("KINDS", "blind").split(","),
        int(env.get("LIMIT", "0")),
    )
    database_url = env.get("DATABASE_URL", "postgresql://bookrag:bookrag@localhost:5432/bookrag")
    texts = await chunk_texts(database_url, book_id)
    top_k = int(env.get("TOP_K", "6"))
    base_url = env.get("API_URL", "http://localhost:8000")
    async with httpx.AsyncClient(base_url=base_url, timeout=300) as client:
        results = await run_eval(client, book_id, rows, texts, top_k=top_k)
    summary = summarise(results, label=label, book_id=book_id, top_k=top_k)
    write_report(Path(env.get("OUT_DIR", HERE / "results")), label, summary, results)
    print(markdown(summary))


if __name__ == "__main__":
    asyncio.run(main())
