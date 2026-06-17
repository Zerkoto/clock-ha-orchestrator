from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.domain.enums import AttentionReason, AutomationPhase, BookingStatus, ControlMode
from app.domain.models import ManualOverride
from app.domain.state_machine import evaluate_room, evaluate_unassigned_booking
from tests.conftest import booking


def test_pre_arrival_inside_preparation_window(policy, now, room_214) -> None:
    result = evaluate_room(room_214, [booking()], now, policy)

    assert result.phase == AutomationPhase.PRE_ARRIVAL
    assert result.reason == "expected_arrival_inside_preparation_window"


def test_reserved_outside_preparation_window(policy, room_214) -> None:
    early = datetime(2026, 12, 19, 6, 0, tzinfo=ZoneInfo("Europe/Sofia"))

    result = evaluate_room(room_214, [booking()], early, policy)

    assert result.phase == AutomationPhase.RESERVED


def test_checked_in_is_occupied_before_checkout(policy, room_214) -> None:
    current = datetime(2026, 12, 21, 12, 0, tzinfo=ZoneInfo("Europe/Sofia"))

    result = evaluate_room(
        room_214,
        [booking(status=BookingStatus.CHECKED_IN)],
        current,
        policy,
    )

    assert result.phase == AutomationPhase.OCCUPIED


def test_checked_in_after_checkout_time_is_checkout_due(policy, room_214) -> None:
    current = datetime(2026, 12, 24, 12, 0, tzinfo=ZoneInfo("Europe/Sofia"))

    result = evaluate_room(
        room_214,
        [booking(status=BookingStatus.CHECKED_IN)],
        current,
        policy,
    )

    assert result.phase == AutomationPhase.CHECKOUT_DUE


def test_canceled_booking_returns_vacant(policy, now, room_214) -> None:
    result = evaluate_room(room_214, [booking(status=BookingStatus.CANCELED)], now, policy)

    assert result.phase == AutomationPhase.VACANT


def test_unassigned_arrival_gets_attention_without_room_intent(policy, now) -> None:
    unassigned = booking(room_id=None, room_number=None)

    result = evaluate_unassigned_booking(unassigned, now, policy)

    assert result is not None
    assert result.phase == AutomationPhase.AWAITING_ASSIGNMENT
    assert result.needs_attention is True
    assert result.attention_reason == AttentionReason.MISSING_PHYSICAL_ROOM
    assert result.room_key is None


def test_room_conflict_suppresses_normal_phase(policy, now, room_214) -> None:
    result = evaluate_room(
        room_214,
        [
            booking(clock_booking_id="booking-1"),
            booking(clock_booking_id="booking-2", arrival=date(2026, 12, 21)),
        ],
        now + timedelta(days=1),
        policy,
    )

    assert result.phase == AutomationPhase.CONFLICT
    assert result.needs_attention is True


def test_manual_override_takes_precedence(policy, now, room_214) -> None:
    override = ManualOverride(
        control_mode=ControlMode.MANUAL,
        expires_at=now + timedelta(hours=2),
    )

    result = evaluate_room(room_214, [booking()], now, policy, override)

    assert result.phase == AutomationPhase.MANUAL_OVERRIDE
