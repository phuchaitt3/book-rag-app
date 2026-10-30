"""Upload a book and list the library."""

import asyncio
import uuid
from datetime import datetime
from typing import Annotated

import procrastinate
import pypdfium2 as pdfium
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from book_rag_api.config import Settings
from book_rag_api.jobs import enqueue_ingestion
from book_rag_api.models import Book
from book_rag_api.storage import ObjectStorage

router = APIRouter(prefix="/books", tags=["books"])

_CHUNK = 1024 * 1024


class BookOut(BaseModel):
    id: uuid.UUID
    title: str
    author: str | None
    language: str
    page_count: int | None
    created_at: datetime


class UploadedBook(BaseModel):
    book: BookOut
    job_id: uuid.UUID


def _engine(request: Request) -> AsyncEngine:
    engine: AsyncEngine = request.app.state.engine
    return engine


def _storage(request: Request) -> ObjectStorage:
    storage: ObjectStorage = request.app.state.storage
    return storage


def _queue(request: Request) -> procrastinate.App:
    queue: procrastinate.App = request.app.state.queue
    return queue


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _count_pages(data: bytes) -> int:
    try:
        doc = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "not a readable PDF") from error
    try:
        return len(doc)
    finally:
        doc.close()


async def _read_capped(file: UploadFile, limit: int) -> bytes:
    """Read the upload, stopping as soon as it passes `limit` bytes."""
    parts: list[bytes] = []
    size = 0
    while chunk := await file.read(_CHUNK):
        size += len(chunk)
        if size > limit:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE, f"file is larger than {limit} bytes"
            )
        parts.append(chunk)
    return b"".join(parts)


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_book(
    file: Annotated[UploadFile, File()],
    engine: Annotated[AsyncEngine, Depends(_engine)],
    storage: Annotated[ObjectStorage, Depends(_storage)],
    queue: Annotated[procrastinate.App, Depends(_queue)],
    settings: Annotated[Settings, Depends(_settings)],
    title: Annotated[str | None, Form()] = None,
    author: Annotated[str | None, Form()] = None,
    language: Annotated[str, Form(max_length=8)] = "vi",
) -> UploadedBook:
    """Store the PDF, create the book and queue its ingestion."""
    data = await _read_capped(file, settings.max_upload_bytes)
    if not data.startswith(b"%PDF-"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "file is not a PDF")
    pages = await asyncio.to_thread(_count_pages, data)
    if pages > settings.max_upload_pages:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"PDF has {pages} pages; the limit is {settings.max_upload_pages}",
        )

    book_id = uuid.uuid4()
    key = f"books/{book_id}/original.pdf"
    await storage.put(key, data)
    fallback = (file.filename or "Untitled").removesuffix(".pdf")
    async with AsyncSession(engine) as session:
        book = Book(
            id=book_id,
            title=(title or fallback).strip() or fallback,
            author=author,
            language=language,
            storage_key=key,
            page_count=pages,
        )
        session.add(book)
        await session.commit()
        await session.refresh(book)
        out = BookOut.model_validate(book, from_attributes=True)
    job_id = await enqueue_ingestion(engine, queue, book_id)
    return UploadedBook(book=out, job_id=job_id)


@router.get("")
async def list_books(engine: Annotated[AsyncEngine, Depends(_engine)]) -> list[BookOut]:
    """All books, newest first."""
    async with AsyncSession(engine) as session:
        books = (await session.scalars(select(Book).order_by(Book.created_at.desc()))).all()
    return [BookOut.model_validate(b, from_attributes=True) for b in books]
