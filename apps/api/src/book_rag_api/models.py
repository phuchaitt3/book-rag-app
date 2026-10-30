import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Must match the embedder behind the provider interface (T13). bge-m3 produces 1024.
EMBEDDING_DIM = 1024

JOB_STATUSES = ("queued", "running", "succeeded", "failed")


class Base(DeclarativeBase):
    pass


class Book(Base):
    __tablename__ = "books"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(8), default="vi", server_default="vi")
    # Object-storage key of the uploaded PDF.
    storage_key: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sections: Mapped[list["Section"]] = relationship(back_populates="book", cascade="all, delete")
    chunks: Mapped[list["Chunk"]] = relationship(back_populates="book", cascade="all, delete")
    jobs: Mapped[list["IngestionJob"]] = relationship(back_populates="book", cascade="all, delete")


class Section(Base):
    """A heading in a book's table of contents; `parent_id` makes the tree."""

    __tablename__ = "sections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    book_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("books.id", ondelete="CASCADE"), index=True
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sections.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(Text)
    # Human-readable path, e.g. "Chương 2 > 2.1 Mở đầu".
    path: Mapped[str] = mapped_column(Text)
    level: Mapped[int] = mapped_column(Integer)
    # Position among all sections of the book, in reading order.
    ordinal: Mapped[int] = mapped_column(Integer)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)

    book: Mapped[Book] = relationship(back_populates="sections")

    __table_args__ = (UniqueConstraint("book_id", "ordinal", name="uq_sections_book_id_ordinal"),)


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    book_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("books.id", ondelete="CASCADE"), index=True
    )
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sections.id", ondelete="SET NULL"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(Integer)
    # Copied from the section so a citation needs no join.
    section_path: Mapped[str | None] = mapped_column(Text)
    # Null until the ingestion worker embeds the chunk.
    embedding: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    # 'simple' config: no stemming or stop words, so it works for Vietnamese without an extension.
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple', text)", persisted=True)
    )

    book: Mapped[Book] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("book_id", "ordinal", name="uq_chunks_book_id_ordinal"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
    )


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    book_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("books.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="queued", server_default="queued")
    # Current step while running: "parse", "chunk" or "embed".
    stage: Mapped[str | None] = mapped_column(String(16))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    book: Mapped[Book] = relationship(back_populates="jobs")

    __table_args__ = (
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in JOB_STATUSES) + ")",
            name="ck_ingestion_jobs_status",
        ),
    )
