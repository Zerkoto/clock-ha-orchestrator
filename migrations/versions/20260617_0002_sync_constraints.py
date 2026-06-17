"""Refine sync uniqueness constraints.

Revision ID: 20260617_0002
Revises: 20260617_0001
Create Date: 2026-06-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260617_0002"
down_revision: str | None = "20260617_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "booking_room_assignments_booking_id_is_current_key",
        "booking_room_assignments",
        type_="unique",
    )
    op.create_index(
        "uq_booking_room_assignments_current",
        "booking_room_assignments",
        ["booking_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    op.create_unique_constraint("uq_rooms_property_key", "rooms", ["property_id", "key"])
    op.create_unique_constraint(
        "uq_sync_cursors_property_source",
        "sync_cursors",
        ["property_id", "source"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_sync_cursors_property_source", "sync_cursors", type_="unique")
    op.drop_constraint("uq_rooms_property_key", "rooms", type_="unique")
    op.drop_index("uq_booking_room_assignments_current", table_name="booking_room_assignments")
    op.create_unique_constraint(
        "booking_room_assignments_booking_id_is_current_key",
        "booking_room_assignments",
        ["booking_id", "is_current"],
    )
