"""Bind manual overrides to booking checkout boundaries.

Revision ID: 20260618_0004
Revises: 20260617_0003
Create Date: 2026-06-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260618_0004"
down_revision: str | None = "20260617_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "room_policy_overrides",
        sa.Column("booking_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "room_policy_overrides",
        sa.Column("checkout_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_room_policy_overrides_booking_id",
        "room_policy_overrides",
        "bookings",
        ["booking_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_room_policy_overrides_booking_id",
        "room_policy_overrides",
        type_="foreignkey",
    )
    op.drop_column("room_policy_overrides", "checkout_at")
    op.drop_column("room_policy_overrides", "booking_id")
