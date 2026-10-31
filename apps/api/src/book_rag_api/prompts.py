"""Prompt templates for answering from retrieved passages."""

from collections.abc import Sequence

from book_rag.providers import Message
from book_rag.retrieval import RetrievedChunk

SYSTEM_PROMPT = (
    "You answer questions about one book using only the numbered passages you are given. "
    "Cite the passages you use with their number in square brackets, like [1] or [2][3]. "
    "If the passages do not contain the answer, say so plainly instead of guessing. "
    "Answer in the language of the question."
)

NO_PASSAGES_REPLY = "I found no passages in this book that match the question."


def format_passage(number: int, chunk: RetrievedChunk) -> str:
    place = ", ".join(
        part
        for part in (
            chunk.section_path,
            f"page {chunk.page}" if chunk.page is not None else None,
        )
        if part
    )
    header = f"[{number}] ({place})" if place else f"[{number}]"
    return f"{header}\n{chunk.text}"


def build_messages(
    question: str, book_title: str, chunks: Sequence[RetrievedChunk]
) -> list[Message]:
    passages = "\n\n".join(format_passage(n, c) for n, c in enumerate(chunks, start=1))
    user = f"Book: {book_title}\n\nPassages:\n{passages}\n\nQuestion: {question}"
    return [Message("system", SYSTEM_PROMPT), Message("user", user)]
