"""A client that goes away cancels the model call; shutdown waits for streams (#228)."""

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator, Sequence

from book_rag.providers import FakeLLM, Message
from book_rag.retrieval import RetrievedChunk
from book_rag_api.draining import StreamTracker
from book_rag_api.metrics import Metrics
from book_rag_api.models import Book
from book_rag_api.routers.chat import answer_events


class WatchedLLM:
    """A fake model that records whether its stream ran to the end or was closed early."""

    def __init__(self, inner: FakeLLM) -> None:
        self.inner = inner
        self.pieces = 0
        self.second_piece = asyncio.Event()
        self.finished = False
        self.closed_early = False

    async def stream(self, messages: Sequence[Message]) -> AsyncIterator[str]:
        try:
            async for piece in self.inner.stream(messages):
                self.pieces += 1
                if self.pieces == 2:
                    self.second_piece.set()
                yield piece
            self.finished = True
        except BaseException:
            self.closed_early = True
            raise


def one_chunk() -> RetrievedChunk:
    return RetrievedChunk(
        id=uuid.uuid4(),
        text="Sông Hồng chảy qua Hà Nội",
        section_path="Chương 1",
        page=1,
        score=0.9,
    )


async def consume(events: AsyncIterator[str]) -> None:
    async for _ in events:
        pass


async def cancel_and_wait(task: "asyncio.Task[None]") -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert task.cancelled()


async def test_disconnect_cancels_the_model_before_it_finishes() -> None:
    llm = WatchedLLM(FakeLLM("một hai ba bốn năm sáu bảy tám chín mười " * 5, token_delay=0.05))
    metrics = Metrics()
    book = Book(id=uuid.uuid4(), title="Sách thử")
    task = asyncio.create_task(
        consume(answer_events(llm, book, "câu hỏi", [one_chunk()], metrics=metrics))
    )
    async with asyncio.timeout(5):
        await llm.second_piece.wait()
    await cancel_and_wait(task)  # what the server does when the client disconnects
    assert llm.closed_early
    assert not llm.finished
    assert llm.pieces < 50
    assert "chat_client_disconnects_total 1.0" in metrics.render().decode()

    pieces = llm.pieces
    await asyncio.sleep(0.2)
    assert llm.pieces == pieces  # nothing keeps generating after the cancel


async def test_a_finished_answer_is_not_counted_as_a_disconnect() -> None:
    llm = WatchedLLM(FakeLLM("một hai ba"))
    metrics = Metrics()
    book = Book(id=uuid.uuid4(), title="Sách thử")
    await consume(answer_events(llm, book, "câu hỏi", [one_chunk()], metrics=metrics))
    assert llm.finished
    assert "chat_client_disconnects_total 0.0" in metrics.render().decode()


async def test_drain_waits_for_the_active_stream_then_returns() -> None:
    tracker = StreamTracker()
    llm = FakeLLM("một hai ba bốn", token_delay=0.05)
    task = asyncio.create_task(consume(tracker.wrap(llm.stream([]))))
    await asyncio.sleep(0.01)
    assert tracker.active == 1
    assert await tracker.drain(5) == 0
    assert tracker.draining
    await task


async def test_drain_gives_up_after_the_timeout() -> None:
    tracker = StreamTracker()
    llm = FakeLLM("một hai ba bốn", first_token_delay=30)
    task = asyncio.create_task(consume(tracker.wrap(llm.stream([]))))
    await asyncio.sleep(0.01)
    assert await tracker.drain(0.05) == 1
    await cancel_and_wait(task)
    assert tracker.active == 0
