from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.domain.enums import BookingStatus
from app.persistence import models as db
from app.system.state import build_system_state


def build_engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db.Base.metadata.create_all(engine)
    return engine


def test_system_state_counts_today_in_property_timezone() -> None:
    engine = build_engine()
    property_id = UUID("00000000-0000-0000-0000-000000000001")
    booking_id = UUID("00000000-0000-0000-0000-000000000002")
    now = datetime(2026, 6, 17, 22, 30, tzinfo=UTC)
    with Session(engine) as session, session.begin():
        session.add(
            db.Property(
                id=property_id,
                key="local_stay_razlog",
                name="Local Stay Hotel & Suites",
                timezone="Europe/Sofia",
            )
        )
        session.add(
            db.Booking(
                id=booking_id,
                property_id=property_id,
                clock_booking_id="booking-1",
                booking_status=BookingStatus.EXPECTED.value,
                source_booking_status=BookingStatus.EXPECTED.value,
                arrival_date=date(2026, 6, 18),
                departure_date=date(2026, 6, 20),
                first_seen_at=now,
                last_seen_at=now,
                payload_hash="abc",
                needs_attention=False,
                attention_reason="none",
            )
        )

    with Session(engine) as session:
        state = build_system_state(
            session,
            property_key="local_stay_razlog",
            now=now,
            mqtt_connected=True,
        )

    assert state["arrivals_today"] == 1
