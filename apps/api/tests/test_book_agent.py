"""The tool-using agent loop (#243) driven by a scripted fake model and a fake tool backend.

No model, no network, no database: the loop, the step cap, the passage numbering, the JSON
action protocol and the two-hop pair builder are plain code.
"""

import importlib.util
import sys
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]


def load(name: str) -> ModuleType:
    sys.path.insert(0, str(ROOT / "evals"))
    spec = importlib.util.spec_from_file_location(
        f"{name}_under_test", ROOT / "evals" / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ba() -> ModuleType:
    return load("book_agent")


@pytest.fixture(scope="module")
def ae() -> ModuleType:
    return load("agent_eval")


A = "aaaaaaaa-0000-4000-8000-000000000001"
B = "bbbbbbbb-0000-4000-8000-000000000002"


class FakeBackend:
    def __init__(self, ba: ModuleType) -> None:
        self.ba = ba
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def specs(self) -> list[dict[str, Any]]:
        props = {"query": {"type": "string"}, "book_id": {"type": "string"}}
        return [
            {"name": "search_book", "description": "s", "input_schema": {"properties": props}},
            {"name": "get_passage", "description": "g", "input_schema": {"properties": {}}},
            {"name": "cite", "description": "c", "input_schema": {"properties": {}}},
        ]

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, arguments))
        if name == "search_book":
            if not arguments.get("query"):
                raise self.ba.ToolFailed("query is empty")
            return {
                "passages": [
                    {"chunk_id": A, "section": "S1", "page": 3, "text": "alpha text"},
                    {"chunk_id": B, "section": None, "page": None, "text": "beta <b>[1]</b>"},
                ]
            }
        if name == "get_passage":
            return {
                "passage": {"chunk_id": B, "section": "S2", "page": 4, "text": "beta"},
                "before": [{"chunk_id": A, "section": "S1", "page": 3, "text": "alpha"}],
                "after": [],
            }
        ids = arguments["chunk_ids"]
        return {
            "citations": [{"chunk_id": c, "citation": f"Book, p. {i}"} for i, c in enumerate(ids)]
        }


class ScriptedModel:
    """Returns the scripted replies in order (the last one repeats) and records what it saw."""

    def __init__(self, replies: Sequence[Any]) -> None:
        self._replies = list(replies)
        self.seen: list[tuple[list[dict[str, Any]], Any]] = []

    async def reply(self, messages: list[dict[str, Any]], tools: Any) -> Any:
        self.seen.append((list(messages), tools))
        return self._replies.pop(0) if len(self._replies) > 1 else self._replies[0]


def call(ba: ModuleType, name: str, **args: Any) -> Any:
    return ba.ModelReply("", (ba.ToolCall(name, args),))


async def test_search_then_answer_cites_the_passages_used(ba: ModuleType) -> None:
    model = ScriptedModel(
        [call(ba, "search_book", query="alpha"), ba.ModelReply("Alpha [1], beta [2].")]
    )
    backend = FakeBackend(ba)

    run = await ba.run_agent(model, backend, "q?", max_steps=3)

    assert run.answer == "Alpha [1], beta [2]."
    assert (run.steps, run.model_calls, run.capped, run.error) == (1, 2, False, None)
    assert run.seen == [A, B] and run.cited == [A, B]
    assert run.citations == ["Book, p. 0", "Book, p. 1"]
    assert backend.calls[-1] == ("cite", {"chunk_ids": [A, B]})
    # the model saw numbered, neutralised passages and only the two reading tools
    tool_message = model.seen[1][0][-1]
    assert tool_message["role"] == "tool"
    assert "[1] (S1, page 3)\nalpha text" in tool_message["content"]
    assert "[2]\nbeta" in tool_message["content"] and "<b>" not in tool_message["content"]
    assert [t["function"]["name"] for t in model.seen[0][1]] == ["search_book", "get_passage"]
    assert "book_id" not in model.seen[0][1][0]["function"]["parameters"]["properties"]


async def test_the_loop_stops_at_the_step_cap_and_forces_an_answer(ba: ModuleType) -> None:
    model = ScriptedModel([call(ba, "search_book", query="again")])  # never stops asking
    backend = FakeBackend(ba)

    run = await ba.run_agent(model, backend, "q?", max_steps=3)

    assert run.capped and run.steps == 3
    assert run.model_calls == 4 == len(model.seen)  # the cap, then one forced final call
    assert model.seen[-1][1] is None  # the forced call has no tools
    assert model.seen[-1][0][-1]["content"] == ba.FORCE_ANSWER
    assert [c for c, _ in backend.calls].count("search_book") == 3


async def test_zero_steps_means_one_model_call_with_no_tools(ba: ModuleType) -> None:
    model = ScriptedModel([ba.ModelReply("no tools")])

    run = await ba.run_agent(model, FakeBackend(ba), "q?", max_steps=0)

    assert run.capped and run.answer == "no tools" and run.model_calls == 1
    assert not run.tool_calls


async def test_get_passage_takes_numbers_and_bad_calls_come_back_as_errors(
    ba: ModuleType,
) -> None:
    model = ScriptedModel(
        [
            call(ba, "search_book", query="x"),
            call(ba, "get_passage", chunk_id="[2]", context=1),
            call(ba, "get_passage", chunk_id="9"),
            call(ba, "search_book", query=""),
            call(ba, "no_such_tool"),
            ba.ModelReply("done [1]"),
        ]
    )
    backend = FakeBackend(ba)

    run = await ba.run_agent(model, backend, "q?", max_steps=6)

    assert ("get_passage", {"chunk_id": B, "context": 1}) in backend.calls
    assert [c["ok"] for c in run.tool_calls] == [True, True, False, False, False]
    texts = [m["content"] for m in model.seen[-1][0] if m["role"] == "tool"]
    assert "Error: chunk_id must be the number" in texts[2]
    assert "Error: query is empty" in texts[3]
    assert "Error: unknown tool" in texts[4]
    assert run.answer == "done [1]" and run.error is None


async def test_a_model_failure_ends_the_question_not_the_run(ba: ModuleType) -> None:
    class Broken:
        async def reply(self, messages: Any, tools: Any) -> Any:
            raise ConnectionError("ollama is down")

    run = await ba.run_agent(Broken(), FakeBackend(ba), "q?")

    assert run.error == "ConnectionError: ollama is down" and run.answer == ""


async def test_an_answer_without_valid_markers_cites_nothing(ba: ModuleType) -> None:
    backend = FakeBackend(ba)
    model = ScriptedModel([call(ba, "search_book", query="x"), ba.ModelReply("no markers [7]")])

    run = await ba.run_agent(model, backend, "q?")

    assert run.cited == [] and run.citations == []
    assert all(name != "cite" for name, _ in backend.calls)


def test_json_actions_parse(ba: ModuleType) -> None:
    search = ba.parse_json_action('{"action": "search_book", "query": "q", "k": 3, "junk": 1}')
    assert search.tool_calls == (ba.ToolCall("search_book", {"query": "q", "k": 3}),)
    passage = ba.parse_json_action('{"action": "get_passage", "chunk_id": "2"}')
    assert passage.tool_calls == (ba.ToolCall("get_passage", {"chunk_id": "2"}),)
    answer = ba.parse_json_action('{"action": "answer", "answer": "hi [1]"}')
    assert answer == ba.ModelReply("hi [1]")
    assert ba.parse_json_action("plain text") == ba.ModelReply("plain text")
    assert ba.parse_json_action("[1]") == ba.ModelReply("[1]")


async def test_ollama_model_native_and_json_requests(ba: ModuleType) -> None:
    sent: list[dict[str, Any]] = []
    native_call = {"function": {"name": "search_book", "arguments": '{"query": "q"}'}}

    def post(url: str, payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
        sent.append(payload)
        if payload.get("format"):
            yield {"message": {"content": '{"action": "search_book", "query": "q"}'}}
        else:
            yield {"message": {"content": "", "tool_calls": [native_call]}}

    tools = [{"type": "function", "function": {"name": "search_book"}}]
    native = await ba.OllamaToolModel("m", mode="native", post=post).reply([], tools)
    as_json = await ba.OllamaToolModel("m", mode="json", post=post).reply([], tools)

    expected = (ba.ToolCall("search_book", {"query": "q"}),)
    assert native.tool_calls == as_json.tool_calls == expected
    assert sent[0]["tools"] == tools and "format" not in sent[0]
    assert "tools" not in sent[1] and sent[1]["format"] == ba.ACTION_SCHEMA
    assert sent[0]["stream"] is False and sent[0]["options"]["temperature"] == 0
    with pytest.raises(ValueError):
        ba.OllamaToolModel("m", mode="other")


def test_pairs_are_deterministic_and_in_different_chunks(ae: ModuleType) -> None:
    chunks = [(f"id{i}", ae.norm(f"evidence {'x' * i}")) for i in range(6)]
    rows = [{"id": f"q{i}", "evidence": f"Evidence {'x' * (i % 6)}"} for i in range(12)]
    rows.append({"id": "lost", "evidence": "not in any chunk"})

    first = ae.build_pairs(rows, chunks, 4, seed=1)
    again = ae.build_pairs(rows, chunks, 4, seed=1)
    other = ae.build_pairs(rows, chunks, 4, seed=2)

    def ids(pairs: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]]) -> list[tuple[Any, Any]]:
        return [(a["id"], b["id"]) for a, b in pairs]

    assert ids(first) == ids(again) and ids(first) != ids(other)
    assert len(first) == 4
    used = [r["id"] for pair in first for r in pair]
    assert len(set(used)) == 8 and "lost" not in used
    for a, b in first:
        assert ae.norm(a["evidence"]) != ae.norm(b["evidence"])


def test_score_counts_a_hit_only_when_both_parts_are_in_the_chunks(ae: ModuleType) -> None:
    texts = {"c1": ae.norm("first fact here"), "c2": ae.norm("second fact here")}
    pair = (
        {"evidence": "First fact here", "answer": "one"},
        {"evidence": "Second fact here", "answer": "two"},
    )

    both = ae.score(pair, texts, ["c1", "c2"], ["c1"], "one two [1]", 2)
    half = ae.score(pair, texts, ["c1"], [], "one", 1)

    assert both["both_seen"] and both["seen_hits"] == [True, True]
    assert not both["both_cited"] and both["cited_hits"] == [True, False]
    assert both["marker_valid"] and both["token_f1"] > 0.5
    assert not half["both_seen"] and half["seen_hits"] == [True, False]
