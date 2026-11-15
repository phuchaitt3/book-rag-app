"""page_reads (text read from image-only pages) and ingestion_jobs.pages_read (#272)

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-15 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "page_reads",
        sa.Column(
            "book_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("books.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("page", sa.Integer(), primary_key=True),
        sa.Column("reader", sa.String(length=32), primary_key=True),
        sa.Column("reader_version", sa.String(length=64), primary_key=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.add_column(
        "ingestion_jobs",
        sa.Column("pages_read", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("ingestion_jobs", "pages_read")
    op.drop_table("page_reads")
