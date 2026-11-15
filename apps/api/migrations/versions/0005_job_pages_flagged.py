"""ingestion_jobs.pages_flagged: pages the parser flagged as needing reading (#270)

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-15 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ingestion_jobs",
        sa.Column("pages_flagged", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("ingestion_jobs", "pages_flagged")
