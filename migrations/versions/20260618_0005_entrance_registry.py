"""Add entrance-aware room registry fields.

Revision ID: 20260618_0005
Revises: 20260618_0004
Create Date: 2026-06-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260618_0005"
down_revision: str | None = "20260618_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("rooms", sa.Column("entrance_key", sa.String(length=120), nullable=True))
    op.execute("UPDATE rooms SET entrance_key = 'legacy_unassigned'")
    op.alter_column("rooms", "entrance_key", existing_type=sa.String(length=120), nullable=False)
    op.alter_column("rooms", "floor", existing_type=sa.String(length=80), nullable=True)
    op.create_index(
        "ix_rooms_property_entrance_key",
        "rooms",
        ["property_id", "entrance_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_rooms_property_entrance_key", table_name="rooms")
    op.execute("UPDATE rooms SET floor = COALESCE(floor, entrance_key, 'legacy')")
    op.alter_column("rooms", "floor", existing_type=sa.String(length=80), nullable=False)
    op.drop_column("rooms", "entrance_key")
