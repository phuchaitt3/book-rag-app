"""The abstain decision and the not-found stream, without a database (#222)."""

import json
from uuid import uuid4

from book_rag.providers import FakeLLM
from book_rag.retrieval import RetrievedChunk
from book_rag_api.config import Settings
from book_rag_api.metrics import Metrics
from book_rag_api.models import Book
from book_rag_api.prompts import NOT_FOUND_REPLY
from book_rag_api.routers.chat import abstain_reason, answer_events


def chunk(score: float, *, reranked: bool) -> RetrievedChunk:
    return RetrievedChunk(
        id=uuid4(), text="t", page=1, section_path=None, score=score, reranked=reranked
    )


SETTINGS = Settings.model_construct(abstain_below_reranked=0.3, abstain_below_fused=0.02)


def test_no_passages_abstains() -> None:
    assert abstain_reason([], SETTINGS) == "no_passages"


def test_each_scale_uses_its_own_threshold() -> None:
    assert abstain_reason([chunk(0.1, reranked=True)], SETTINGS) == "low_score"
    assert abstain_reason([chunk(0.5, reranked=True)], SETTINGS) is None
    # 0.1 is above the fused threshold, and would be below the reranked one.
    assert abstain_reason([chunk(0.1, reranked=False)], SETTINGS) is None
    assert abstain_reason([chunk(0.01, reranked=False)], SETTINGS) == "low_score"


def test_a_score_equal_to_the_threshold_answers() -> None:
    assert abstain_reason([chunk(0.3, reranked=True)], SETTINGS) is None


def test_none_turns_a_threshold_off() -> None:
    off = Settings.model_construct(abstain_below_reranked=None, abstain_below_fused=None)
    assert abstain_reason([chunk(0.0, reranked=True)], off) is None
    assert abstain_reason([chunk(0.0, reranked=False)], off) is None


async def test_abstain_stream_has_no_citations_and_never_reaches_the_model() -> None:
    class Boom:
        def stream(self, messages: object) -> object:
            raise AssertionError("the model must not be called")

    metrics = Metrics()
    book = Book(id=uuid4(), title="Sach")
    text = "".join(
        [
            piece
            async for piece in answer_events(
                Boom(),  # type: ignore[arg-type]
                book,
                "q",
                [chunk(0.0, reranked=True)],
                abstain="low_score",
                metrics=metrics,
            )
        ]
    )
    blocks = [b.split("\n") for b in text.strip().split("\n\n")]
    assert [b[0] for b in blocks] == ["event: citations", "event: token", "event: done"]
    assert json.loads(blocks[0][1][6:]) == []
    assert json.loads(blocks[1][1][6:]) == {"text": NOT_FOUND_REPLY}
    assert json.loads(blocks[2][1][6:]) == {"abstained": True}
    assert 'chat_abstentions_total{reason="low_score"} 1.0' in metrics.render().decode()


async def test_a_normal_stream_is_not_abstained() -> None:
    book = Book(id=uuid4(), title="Sach")
    text = "".join(
        [p async for p in answer_events(FakeLLM("a [1]"), book, "q", [chunk(0.9, reranked=True)])]
    )
    assert text.rstrip().endswith('data: {"abstained": false}')
