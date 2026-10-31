"""Ask a question about one book; the answer streams back as server-sent events.

Events, in order: `citations` (once, before the first token), `token` (many), then `done`.
If the model fails part-way, `error` is sent instead of `done`.
"""

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from book_rag.providers import LLM
from book_rag.retrieval import HybridRetriever, RetrievedChunk
from book_rag_api.models import Book
from book_rag_api.prompts import NO_PASSAGES_REPLY, build_messages

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
        )
        for n, c in enumerate(chunks, start=1)
    ]


async def answer_events(
    llm: LLM, book: Book, question: str, chunks: list[RetrievedChunk]
) -> AsyncIterator[str]:
    citations = citations_for(book, chunks)
    yield sse("citations", [c.model_dump(mode="json") for c in citations])
    if not chunks:
        yield sse("token", {"text": NO_PASSAGES_REPLY})
        yield sse("done", {})
        return
    try:
        async for piece in llm.stream(build_messages(question, book.title, chunks)):
            yield sse("token", {"text": piece})
    except Exception:
        log.exception("model failed while streaming an answer")
        yield sse("error", {"message": "the model failed; try again"})
        return
    yield sse("done", {})


@router.post("/{book_id}/chat")
async def chat(book_id: uuid.UUID, body: ChatRequest, request: Request) -> StreamingResponse:
    engine: AsyncEngine = request.app.state.engine
    retriever: HybridRetriever = request.app.state.retriever
    llm: LLM = request.app.state.llm
    async with AsyncSession(engine, expire_on_commit=False) as session:
        book = await session.get(Book, book_id)
    if book is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "book not found")
    chunks = await retriever.retrieve(book_id, body.question, top_k=body.top_k)
    return StreamingResponse(
        answer_events(llm, book, body.question, chunks),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
