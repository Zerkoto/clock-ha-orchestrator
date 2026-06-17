from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSONB}


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    key: Mapped[str] = mapped_column(String(120), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    timezone: Mapped[str] = mapped_column(String(80), default="Europe/Sofia")


class Room(Base):
    __tablename__ = "rooms"
    __table_args__ = (UniqueConstraint("property_id", "clock_room_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    property_id: Mapped[UUID] = mapped_column(ForeignKey("properties.id"))
    key: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(255))
    floor: Mapped[str] = mapped_column(String(80))
    clock_room_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (UniqueConstraint("property_id", "clock_booking_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    property_id: Mapped[UUID] = mapped_column(ForeignKey("properties.id"))
    clock_booking_id: Mapped[str] = mapped_column(String(120))
    booking_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    external_source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    external_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    booking_status: Mapped[str] = mapped_column(String(80))
    source_booking_status: Mapped[str] = mapped_column(String(120))
    arrival_date: Mapped[date] = mapped_column(Date)
    departure_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    room_type_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    room_type_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    adults: Mapped[int | None] = mapped_column(Integer, nullable=True)
    children: Mapped[int | None] = mapped_column(Integer, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload_hash: Mapped[str] = mapped_column(String(64))
    needs_attention: Mapped[bool] = mapped_column(Boolean, default=False)
    attention_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)

    assignments: Mapped[list[BookingRoomAssignment]] = relationship(back_populates="booking")


class BookingRoomAssignment(Base):
    __tablename__ = "booking_room_assignments"
    __table_args__ = (UniqueConstraint("booking_id", "is_current"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    booking_id: Mapped[UUID] = mapped_column(ForeignKey("bookings.id"))
    room_id: Mapped[UUID | None] = mapped_column(ForeignKey("rooms.id"), nullable=True)
    clock_room_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    physical_room_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)

    booking: Mapped[Booking] = relationship(back_populates="assignments")


class RoomState(Base):
    __tablename__ = "room_states"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    room_id: Mapped[UUID] = mapped_column(ForeignKey("rooms.id"))
    automation_phase: Mapped[str] = mapped_column(String(80))
    booking_id: Mapped[UUID | None] = mapped_column(ForeignKey("bookings.id"), nullable=True)
    needs_attention: Mapped[bool] = mapped_column(Boolean, default=False)
    attention_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    intent_version: Mapped[int] = mapped_column(Integer)
    payload_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RoomPolicyOverride(Base):
    __tablename__ = "room_policy_overrides"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    room_id: Mapped[UUID] = mapped_column(ForeignKey("rooms.id"))
    command_id: Mapped[UUID] = mapped_column(unique=True)
    control_mode: Mapped[str] = mapped_column(String(80))
    hvac_mode: Mapped[str | None] = mapped_column(String(80), nullable=True)
    target_temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    water_heater_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    until_checkout: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)


class SyncCursor(Base):
    __tablename__ = "sync_cursors"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    property_id: Mapped[UUID] = mapped_column(ForeignKey("properties.id"))
    source: Mapped[str] = mapped_column(String(80))
    cursor_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    property_id: Mapped[UUID] = mapped_column(ForeignKey("properties.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(80))
    processed_bookings: Mapped[int] = mapped_column(Integer, default=0)
    error_classification: Mapped[str | None] = mapped_column(String(120), nullable=True)
    correlation_id: Mapped[UUID]


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    topic: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]]
    qos: Mapped[int] = mapped_column(Integer, default=1)
    retain: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(80), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    correlation_id: Mapped[UUID]


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    property_id: Mapped[UUID | None] = mapped_column(ForeignKey("properties.id"), nullable=True)
    room_id: Mapped[UUID | None] = mapped_column(ForeignKey("rooms.id"), nullable=True)
    booking_id: Mapped[UUID | None] = mapped_column(ForeignKey("bookings.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(120))
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    correlation_id: Mapped[UUID]
