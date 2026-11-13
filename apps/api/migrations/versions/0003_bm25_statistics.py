"""per-book statistics for BM25: chunks.token_count and book_terms (ADR 0011)

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-14 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chunks", sa.Column("token_count", sa.Integer(), server_default="0", nullable=False)
    )
    op.create_table(
        "book_terms",
        sa.Column("book_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("term", sa.Text(), nullable=False),
        sa.Column("df", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("book_id", "term"),
    )
    # Backfill the books that exist (the same statements as `refresh_book_stats`, all books).
    op.execute(
        "UPDATE chunks SET token_count = "
        "(SELECT coalesce(sum(cardinality(positions)), 0) FROM unnest(tsv))"
    )
    op.execute(
        "INSERT INTO book_terms (book_id, term, df) "
        "SELECT c.book_id, u.lexeme, count(*) FROM chunks c, unnest(c.tsv) u GROUP BY 1, 2"
    )


def downgrade() -> None:
    op.drop_table("book_terms")
    op.drop_column("chunks", "token_count")
