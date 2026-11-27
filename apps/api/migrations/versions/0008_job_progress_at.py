"""ingestion_jobs.progress_at: last page-level progress, for the stuck-job sweep (#274)

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-19 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ingestion_jobs", sa.Column("progress_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("ingestion_jobs", "progress_at")
