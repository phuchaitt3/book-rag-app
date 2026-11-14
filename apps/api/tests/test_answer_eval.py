"""The answer-eval harness (#221) end to end with the fake providers: no model, no network.

The fixture is a small excerpt of the checked book test set (`evals/fixtures/mini-book.json`),
so CI does not need the git-ignored data folder.
"""

import importlib.util
import json
import sys
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from types import ModuleType
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from test_chat import database_url, event_loop_policy, make_client  # noqa: F401

from book_rag.providers import FakeEmbedder, Message
from book_rag_api.models import EMBEDDING_DIM, Book, Chunk

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = json.loads((ROOT / "evals" / "fixtures" / "mini-book.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ae() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "answer_eval_under_test", ROOT / "evals" / "answer_eval.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ScriptedLLM:
    """Answers each fixture question by a fixed script keyed on its position in the fixture."""

    def __init__(self, script: dict[str, str]) -> None:
        self._script = script

    async def stream(self, messages: Sequence[Message]) -> AsyncIterator[str]:
        question = messages[-1].content.rsplit("Question: ", 1)[1]
        reply = self._script[question]
        if reply == "BOOM":
            yield "partial"
            raise RuntimeError("model down")
        yield reply


def scripted(rows: list[dict[str, str]]) -> dict[str, str]:
    """q0 cites [1] with the reference answer, q1 cites a marker that does not exist, q2 has no
    marker, q3 fails mid-stream, the rest answer correctly with [1]."""
    replies = {
        1: lambda r: f"{r['answer']} [9]",
        2: lambda r: r["answer"],
        3: lambda r: "BOOM",
    }
    answerable = [r for r in rows if "answer" in r]
    out = {
        r["question"]: replies.get(i, lambda r: f"{r['answer']} [1]")(r)
        for i, r in enumerate(answerable)
    }
    out.update({r["question"]: "The book does not say. [1]" for r in rows if "answer" not in r})
    return out


@pytest.fixture
async def book(database_url: str) -> tuple[UUID, dict[str, str]]:  # noqa: F811
    engine = create_async_engine(database_url)
    chunks = FIXTURE["chunks"]
    vectors = await FakeEmbedder(EMBEDDING_DIM).embed([c["text"] for c in chunks])
    book = Book(id=uuid4(), title=FIXTURE["book_title"])
    async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
        session.add(book)
        await session.flush()
        session.add_all(
            Chunk(
                book_id=book.id,
                ordinal=c["ordinal"],
                text=c["text"],
                section_path=c["section_path"],
                embedding=v,
            )
            for c, v in zip(chunks, vectors, strict=True)
        )
    async with AsyncSession(engine) as session:
        rows = (
            await session.execute(select(Chunk.id, Chunk.text).where(Chunk.book_id == book.id))
        ).all()
    await engine.dispose()
    return book.id, {str(i): t for i, t in rows}


async def test_fake_run_scores_every_metric(
    ae: ModuleType,
    database_url: str,  # noqa: F811
    book: tuple[UUID, dict[str, str]],
    tmp_path: Path,
) -> None:
    book_id, raw = book
    texts = {i: ae.norm(t) for i, t in raw.items()}
    rows = FIXTURE["questions"]
    async for client in make_client(
        database_url, ScriptedLLM(scripted(rows)), chat_rate_limit=1000
    ):
        results = await ae.run_eval(client, str(book_id), rows, texts, top_k=3)
    summary = ae.summarise(results, label="fake", top_k=3)
    ae.write_report(tmp_path, "fake", summary, results)

    assert summary["questions"] == 7  # six answerable, one unanswerable
    assert summary["format_errors"] == 0
    assert summary["stream_errors"] == 1  # the scripted mid-stream failure
    assert summary["scored_for_hit"] == 6
    assert summary["scored_for_overlap"] == 6
    # Six answers: one cites [9] of three citations (invalid), one fails mid-stream with no marker.
    by_id = {r["id"]: r for r in results}
    answerable = [r["id"] for r in rows if "answer" in r]
    assert by_id[answerable[1]]["citation_valid"] is False
    assert by_id[answerable[2]]["markers"] == 0
    assert by_id[answerable[3]]["stream_error"] is True
    assert by_id[answerable[0]]["token_f1"] > 0.5  # the answer is the reference plus a marker
    assert summary["citation_valid_pct"] == round(100 * 6 / 7, 1)
    assert 0 <= summary["citation_hit_pct"] <= 100
    report = json.loads((tmp_path / "answer-eval-fake.json").read_text(encoding="utf-8"))
    assert report["summary"] == summary
    assert "Citation validity" in (tmp_path / "answer-eval-fake.md").read_text(encoding="utf-8")


def test_scoring_helpers(ae: ModuleType) -> None:
    row = {"id": "q", "question": "?", "answer": "Chữ Nho", "evidence": "xin chào thế giới"}
    texts = {"a": ae.norm("Xin chào, thế giới 12!"), "b": "zzz"}
    cites = [{"chunk_id": "b"}, {"chunk_id": "a"}]

    def body(*events: tuple[str, object]) -> str:
        return "".join(f"event: {n}\ndata: {json.dumps(d)}\n\n" for n, d in events)

    ok = ae.score_stream(
        200,
        body(("citations", cites), ("token", {"text": "chữ nho [2]"}), ("done", {})),
        row,
        texts,
    )
    assert ok["format_error"] is None and ok["citation_valid"] is True
    assert ok["citation_rank"] == 2 and ok["cited_answer_hit"] is True
    assert ok["token_f1"] == 1.0

    cases = {
        "status": (503, ""),
        "no done": (200, body(("citations", cites), ("token", {"text": "x"}))),
        "not citations": (200, body(("token", {"text": "x"}), ("done", {}))),
        "garbage": (200, "hello"),
        "empty": (200, body(("citations", cites), ("done", {}))),
    }
    for name, (status, text) in cases.items():
        assert ae.score_stream(status, text, row, texts)["format_error"], name
    errored = ae.score_stream(
        200,
        body(("citations", cites), ("token", {"text": "x"}), ("error", {"message": "m"})),
        row,
        texts,
    )
    assert errored["stream_error"] is True and errored["format_error"] is None


def test_overlap_counts_repeats_and_ignores_markers(ae: ModuleType) -> None:
    assert ae.overlap("a a b [1]", "a b") == pytest.approx((0.8, 1.0))
    assert ae.overlap("x", "y") == (0.0, 0.0)
