"""books.owner_id: every book belongs to one owner (#230)

Existing books are backfilled to the fixed dev owner `dev-user`. The column has no default, so
code that forgets the owner fails instead of writing to the dev owner.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-15 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEV_OWNER = "dev-user"


def upgrade() -> None:
    op.add_column("books", sa.Column("owner_id", sa.Text(), nullable=True))
    op.execute(sa.text("UPDATE books SET owner_id = :owner").bindparams(owner=DEV_OWNER))
    op.alter_column("books", "owner_id", nullable=False)
    op.create_index("ix_books_owner_id", "books", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_books_owner_id", table_name="books")
    op.drop_column("books", "owner_id")
