"""Ask a question about one book; the answer streams back as server-sent events.

Events, in order: `citations` (once, before the first token), `token` (many), then `done`.
If the model fails part-way, `error` is sent instead of `done`. When the book has no passage
good enough to answer from, the reply is a fixed "not found" text with no citations, the model
is not called, and `done` carries `abstained: true` (#222).
"""

import asyncio
import json
import logging
import math
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from book_rag.providers import LLM
from book_rag.retrieval import HybridRetriever, RetrievedChunk
from book_rag_api.config import Settings
from book_rag_api.draining import StreamTracker
from book_rag_api.metrics import Metrics
from book_rag_api.models import Book, IngestionJob
from book_rag_api.prompts import NO_PASSAGES_REPLY, NOT_FOUND_REPLY, build_messages
from book_rag_api.rate_limit import RateLimiter

router = APIRouter(prefix="/books", tags=["chat"])
log = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    question: Annotated[str, Field(min_length=1, max_length=2000)]
    top_k: Annotated[int, Field(ge=1, le=20)] = 6


class Citation(BaseModel):
    number: int
    chunk_id: uuid.UUID
    book_id: uuid.UUID
    book_title: str
    section: str | None
    page: int | None
    # The passage's relevance score: the reranker's, or the fused score if no reranker ran.
    score: float


class TokenEvent(BaseModel):
    """One piece of the answer text."""

    text: str


class DoneEvent(BaseModel):
    """The answer is complete."""

    # True when the reply is the fixed not-found text, not an answer from the book.
    abstained: bool = False


class ErrorEvent(BaseModel):
    """The model failed part-way; the answer is cut short."""

    message: str


# The payload of each event. OpenAPI cannot describe a stream, so `book_rag_api.openapi`
# adds these to the document's schemas for the web app's generated types.
STREAM_EVENT_MODELS: tuple[type[BaseModel], ...] = (Citation, TokenEvent, DoneEvent, ErrorEvent)


def sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def citations_for(book: Book, chunks: list[RetrievedChunk]) -> list[Citation]:
    return [
        Citation(
            number=n,
            chunk_id=c.id,
            book_id=book.id,
            book_title=book.title,
            section=c.section_path,
            page=c.page,
            score=c.score,
        )
        for n, c in enumerate(chunks, start=1)
    ]


def abstain_reason(chunks: list[RetrievedChunk], settings: Settings) -> str | None:
    """Why the question should get the not-found reply, or None to answer it.

    The best passage is the first (both the fused and the reranked order put it there). Its
    score is compared with the threshold for its own scale; a threshold of None never abstains.
    """
    if not chunks:
        return "no_passages"
    best = chunks[0]
    threshold = settings.abstain_below_reranked if best.reranked else settings.abstain_below_fused
    if threshold is not None and best.score < threshold:
        return "low_score"
    return None


async def with_timeouts(
    pieces: AsyncIterator[str], *, idle: float, total: float
) -> AsyncIterator[str]:
    """Pass `pieces` through; raise TimeoutError if one takes over `idle` seconds or the whole
    stream takes over `total`."""
    iterator = pieces.__aiter__()
    try:
        async with asyncio.timeout(total):
            while True:
                try:
                    piece = await asyncio.wait_for(anext(iterator), idle)
                except StopAsyncIteration:
                    return
                yield piece
    finally:
        aclose = getattr(iterator, "aclose", None)
        if aclose is not None:
            await aclose()


async def answer_events(
    llm: LLM,
    book: Book,
    question: str,
    chunks: list[RetrievedChunk],
    *,
    idle_timeout: float = 30.0,
    total_timeout: float = 180.0,
    abstain: str | None = None,
    metrics: Metrics | None = None,
) -> AsyncIterator[str]:
    if abstain is not None:
        if metrics is not None:
            metrics.abstained(abstain)
        # No citations: the passages found are not what the reply rests on.
        reply = NO_PASSAGES_REPLY if abstain == "no_passages" else NOT_FOUND_REPLY
        yield sse("citations", [])
        yield sse("token", TokenEvent(text=reply).model_dump())
        yield sse("done", DoneEvent(abstained=True).model_dump())
        return
    citations = citations_for(book, chunks)
    yield sse("citations", [c.model_dump(mode="json") for c in citations])
    try:
        stream = llm.stream(build_messages(question, book.title, chunks))
        async for piece in with_timeouts(stream, idle=idle_timeout, total=total_timeout):
            yield sse("token", TokenEvent(text=piece).model_dump())
    except asyncio.CancelledError:
        # The server cancels the response when the client disconnects. Leaving the `async for`
        # closed the model stream (with_timeouts' finally), which stops the call and the
        # tokens it bills for.
        log.info("client disconnected; model call cancelled")
        if metrics is not None:
            metrics.client_disconnected()
        raise
    except TimeoutError:
        log.warning("model stream timed out")
        yield sse("error", ErrorEvent(message="the model took too long; try again").model_dump())
        return
    except Exception:
        log.exception("model failed while streaming an answer")
        yield sse("error", ErrorEvent(message="the model failed; try again").model_dump())
        return
    yield sse("done", DoneEvent().model_dump())


@router.post("/{book_id}/chat")
async def chat(book_id: uuid.UUID, body: ChatRequest, request: Request) -> StreamingResponse:
    engine: AsyncEngine = request.app.state.engine
    retriever: HybridRetriever = request.app.state.retriever
    llm: LLM = request.app.state.llm
    settings: Settings = request.app.state.settings
    limiter: RateLimiter = request.app.state.chat_limiter
    wait = limiter.check(request.client.host if request.client else "unknown")
    if wait is not None:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "too many questions; slow down",
            headers={"Retry-After": str(math.ceil(wait))},
        )
    async with AsyncSession(engine, expire_on_commit=False) as session:
        book = await session.get(Book, book_id)
        latest_job = await session.scalar(
            select(IngestionJob.status)
            .where(IngestionJob.book_id == book_id)
            .order_by(IngestionJob.created_at.desc())
            .limit(1)
        )
    if book is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "book not found")
    # Chunks are committed before their embeddings, and a re-run replaces them, so until the
    # latest job succeeds the search would quietly use part of the book (ADR 0004).
    if latest_job is not None and latest_job != "succeeded":
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"the book is not ready yet: its ingestion is {latest_job}"
        )
    try:
        async with asyncio.timeout(settings.retrieval_timeout):
            chunks = await retriever.retrieve(book_id, body.question, top_k=body.top_k)
    except Exception:
        # The embedder (Ollama) or the search failed before any byte was sent, so a status
        # code can still say so; once the stream starts only an `error` event can.
        log.exception("retrieval failed")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "search is unavailable; try again"
        ) from None
    events = answer_events(
        llm,
        book,
        body.question,
        chunks,
        idle_timeout=settings.llm_idle_timeout,
        total_timeout=settings.llm_total_timeout,
        abstain=abstain_reason(chunks, settings),
        metrics=request.app.state.metrics,
    )
    tracker: StreamTracker = request.app.state.streams
    return StreamingResponse(
        tracker.wrap(events),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
