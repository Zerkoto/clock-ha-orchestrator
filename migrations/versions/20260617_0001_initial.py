"""Initial schema.

Revision ID: 20260617_0001
Revises:
Create Date: 2026-06-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260617_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "properties",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("key", sa.String(length=120), nullable=False, unique=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("timezone", sa.String(length=80), nullable=False),
    )
    op.create_table(
        "rooms",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("property_id", sa.UUID(), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("floor", sa.String(length=80), nullable=False),
        sa.Column("clock_room_id", sa.String(length=120), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("property_id", "clock_room_id"),
    )
    op.create_table(
        "bookings",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("property_id", sa.UUID(), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("clock_booking_id", sa.String(length=120), nullable=False),
        sa.Column("booking_number", sa.String(length=120), nullable=True),
        sa.Column("external_source", sa.String(length=120), nullable=True),
        sa.Column("external_reference", sa.String(length=255), nullable=True),
        sa.Column("booking_status", sa.String(length=80), nullable=False),
        sa.Column("source_booking_status", sa.String(length=120), nullable=False),
        sa.Column("arrival_date", sa.Date(), nullable=False),
        sa.Column("departure_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("room_type_id", sa.String(length=120), nullable=True),
        sa.Column("room_type_name", sa.String(length=255), nullable=True),
        sa.Column("adults", sa.Integer(), nullable=True),
        sa.Column("children", sa.Integer(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("needs_attention", sa.Boolean(), nullable=False),
        sa.Column("attention_reason", sa.String(length=120), nullable=True),
        sa.UniqueConstraint("property_id", "clock_booking_id"),
    )
    op.create_table(
        "booking_room_assignments",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("booking_id", sa.UUID(), sa.ForeignKey("bookings.id"), nullable=False),
        sa.Column("room_id", sa.UUID(), sa.ForeignKey("rooms.id"), nullable=True),
        sa.Column("clock_room_id", sa.String(length=120), nullable=True),
        sa.Column("physical_room_number", sa.String(length=120), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("booking_id", "is_current"),
    )
    op.create_table(
        "room_states",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("room_id", sa.UUID(), sa.ForeignKey("rooms.id"), nullable=False),
        sa.Column("automation_phase", sa.String(length=80), nullable=False),
        sa.Column("booking_id", sa.UUID(), sa.ForeignKey("bookings.id"), nullable=True),
        sa.Column("needs_attention", sa.Boolean(), nullable=False),
        sa.Column("attention_reason", sa.String(length=120), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("intent_version", sa.Integer(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "room_policy_overrides",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("room_id", sa.UUID(), sa.ForeignKey("rooms.id"), nullable=False),
        sa.Column("command_id", sa.UUID(), nullable=False, unique=True),
        sa.Column("control_mode", sa.String(length=80), nullable=False),
        sa.Column("hvac_mode", sa.String(length=80), nullable=True),
        sa.Column("target_temperature_c", sa.Float(), nullable=True),
        sa.Column("water_heater_enabled", sa.Boolean(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("until_checkout", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(length=120), nullable=True),
    )
    op.create_table(
        "sync_cursors",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("property_id", sa.UUID(), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("cursor_value", sa.Text(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "sync_runs",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("property_id", sa.UUID(), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("processed_bookings", sa.Integer(), nullable=False),
        sa.Column("error_classification", sa.String(length=120), nullable=True),
        sa.Column("correlation_id", sa.UUID(), nullable=False),
    )
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("qos", sa.Integer(), nullable=False),
        sa.Column("retain", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("correlation_id", sa.UUID(), nullable=False),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("property_id", sa.UUID(), sa.ForeignKey("properties.id"), nullable=True),
        sa.Column("room_id", sa.UUID(), sa.ForeignKey("rooms.id"), nullable=True),
        sa.Column("booking_id", sa.UUID(), sa.ForeignKey("bookings.id"), nullable=True),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_id", sa.UUID(), nullable=False),
    )


def downgrade() -> None:
    for table in (
        "audit_events",
        "outbox_events",
        "sync_runs",
        "sync_cursors",
        "room_policy_overrides",
        "room_states",
        "booking_room_assignments",
        "bookings",
        "rooms",
        "properties",
    ):
        op.drop_table(table)
