"""Add outbox retry and claim fields.

Revision ID: 20260617_0003
Revises: 20260617_0002
Create Date: 2026-06-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260617_0003"
down_revision: str | None = "20260617_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "outbox_events",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("outbox_events", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column(
        "outbox_events",
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("outbox_events", sa.Column("claimed_by", sa.String(length=120), nullable=True))
    op.create_index(
        "ix_outbox_events_claimable",
        "outbox_events",
        ["status", "next_attempt_at", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_events_claimable", table_name="outbox_events")
    op.drop_column("outbox_events", "claimed_by")
    op.drop_column("outbox_events", "claimed_at")
    op.drop_column("outbox_events", "last_error")
    op.drop_column("outbox_events", "next_attempt_at")
