"""unique (book_id, ordinal) on sections and chunks

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-30 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # No dedupe step: no real database existed when this was written. Before running it on one,
    # check for duplicate (book_id, ordinal) rows, or the constraint creation will fail.
    op.create_unique_constraint("uq_sections_book_id_ordinal", "sections", ["book_id", "ordinal"])
    op.create_unique_constraint("uq_chunks_book_id_ordinal", "chunks", ["book_id", "ordinal"])


def downgrade() -> None:
    op.drop_constraint("uq_chunks_book_id_ordinal", "chunks", type_="unique")
    op.drop_constraint("uq_sections_book_id_ordinal", "sections", type_="unique")
