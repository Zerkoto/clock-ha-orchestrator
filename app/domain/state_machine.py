from __future__ import annotations

from datetime import date, datetime, timedelta

from app.domain.enums import AttentionReason, AutomationPhase, BookingStatus
from app.domain.models import (
    HotelPolicy,
    ManualOverride,
    NormalizedBooking,
    Room,
    RoomStateEvaluation,
)


def arrival_at(booking: NormalizedBooking, policy: HotelPolicy) -> datetime:
    return datetime.combine(
        booking.arrival_date,
        policy.property.default_check_in_time,
        tzinfo=policy.property.tzinfo,
    )


def checkout_at(booking: NormalizedBooking, policy: HotelPolicy) -> datetime:
    return datetime.combine(
        booking.departure_date,
        policy.property.default_check_out_time,
        tzinfo=policy.property.tzinfo,
    )


def bookings_overlap(left: NormalizedBooking, right: NormalizedBooking) -> bool:
    return left.arrival_date < right.departure_date and right.arrival_date < left.departure_date


def active_bookings_for_room(
    room: Room,
    bookings: list[NormalizedBooking],
    on_date: date,
) -> list[NormalizedBooking]:
    room_ids = {value for value in (room.clock_room_id, room.key) if value}
    active: list[NormalizedBooking] = []
    for booking in bookings:
        if not booking.active_for_automation:
            continue
        if booking.physical_room_id not in room_ids and booking.physical_room_number != room.key:
            continue
        if on_date <= booking.departure_date:
            active.append(booking)
    return active


def approaching_unassigned_arrivals(
    bookings: list[NormalizedBooking],
    now: datetime,
    policy: HotelPolicy,
) -> list[NormalizedBooking]:
    lead = timedelta(minutes=policy.automation.pre_arrival_lead_minutes)
    result: list[NormalizedBooking] = []
    for booking in bookings:
        if booking.booking_status != BookingStatus.EXPECTED or booking.has_physical_room:
            continue
        if arrival_at(booking, policy) - lead <= now:
            result.append(booking)
    return result


def evaluate_unassigned_booking(
    booking: NormalizedBooking,
    now: datetime,
    policy: HotelPolicy,
) -> RoomStateEvaluation | None:
    if booking.booking_status != BookingStatus.EXPECTED or booking.has_physical_room:
        return None
    lead_start = arrival_at(booking, policy) - timedelta(
        minutes=policy.automation.pre_arrival_lead_minutes
    )
    if lead_start <= now:
        return RoomStateEvaluation(
            room_key=None,
            phase=AutomationPhase.AWAITING_ASSIGNMENT,
            booking=booking,
            needs_attention=True,
            attention_reason=AttentionReason.MISSING_PHYSICAL_ROOM,
            reason="expected_arrival_inside_preparation_window_without_physical_room",
            effective_from=now,
            expires_at=checkout_at(booking, policy),
        )
    return None


def evaluate_room(
    room: Room,
    bookings: list[NormalizedBooking],
    now: datetime,
    policy: HotelPolicy,
    override: ManualOverride | None = None,
) -> RoomStateEvaluation:
    if not room.enabled:
        return RoomStateEvaluation(
            room_key=room.key,
            phase=AutomationPhase.DISABLED,
            reason="room_disabled_by_configuration",
            effective_from=now,
        )

    candidates = active_bookings_for_room(room, bookings, now.date())
    unknown = [
        booking
        for booking in bookings
        if booking.booking_status == BookingStatus.UNKNOWN
        and (
            booking.physical_room_id == room.clock_room_id
            or booking.physical_room_number == room.key
        )
    ]
    if unknown:
        return RoomStateEvaluation(
            room_key=room.key,
            phase=AutomationPhase.UNKNOWN,
            booking=unknown[0],
            needs_attention=True,
            attention_reason=AttentionReason.UNKNOWN_CLOCK_STATUS,
            reason="unknown_clock_status_suppresses_automatic_actions",
            effective_from=now,
        )

    for index, left in enumerate(candidates):
        for right in candidates[index + 1 :]:
            if bookings_overlap(left, right):
                return RoomStateEvaluation(
                    room_key=room.key,
                    phase=AutomationPhase.CONFLICT,
                    booking=left,
                    needs_attention=True,
                    attention_reason=AttentionReason.OVERLAPPING_ACTIVE_BOOKINGS,
                    reason="overlapping_active_bookings_assigned_to_room",
                    effective_from=now,
                )

    selected = _select_relevant_booking(candidates, now, policy)
    if selected is None:
        return RoomStateEvaluation(
            room_key=room.key,
            phase=AutomationPhase.VACANT,
            reason="no_active_assigned_reservation",
            effective_from=now,
        )

    if override and override.is_active(now, clock_booking_id=selected.clock_booking_id):
        return RoomStateEvaluation(
            room_key=room.key,
            phase=AutomationPhase.MANUAL_OVERRIDE,
            booking=selected,
            reason="valid_manual_override_active",
            effective_from=now,
            expires_at=override.expires_at,
        )

    if selected.booking_status == BookingStatus.CHECKED_IN:
        if now >= checkout_at(selected, policy):
            return RoomStateEvaluation(
                room_key=room.key,
                phase=AutomationPhase.CHECKOUT_DUE,
                booking=selected,
                reason="departure_time_passed_without_clock_checkout",
                effective_from=now,
                expires_at=checkout_at(selected, policy),
            )
        return RoomStateEvaluation(
            room_key=room.key,
            phase=AutomationPhase.OCCUPIED,
            booking=selected,
            reason="clock_reports_guest_checked_in",
            effective_from=now,
            expires_at=checkout_at(selected, policy),
        )

    if selected.booking_status == BookingStatus.EXPECTED:
        lead_start = arrival_at(selected, policy) - timedelta(
            minutes=policy.automation.pre_arrival_lead_minutes
        )
        if now >= lead_start:
            return RoomStateEvaluation(
                room_key=room.key,
                phase=AutomationPhase.PRE_ARRIVAL,
                booking=selected,
                reason="expected_arrival_inside_preparation_window",
                effective_from=lead_start,
                expires_at=checkout_at(selected, policy),
            )
        return RoomStateEvaluation(
            room_key=room.key,
            phase=AutomationPhase.RESERVED,
            booking=selected,
            reason="future_assigned_reservation_outside_preparation_window",
            effective_from=now,
            expires_at=lead_start,
        )

    return RoomStateEvaluation(
        room_key=room.key,
        phase=AutomationPhase.VACANT,
        booking=selected,
        reason="booking_inactive_for_automation",
        effective_from=now,
    )


def _select_relevant_booking(
    bookings: list[NormalizedBooking],
    now: datetime,
    policy: HotelPolicy,
) -> NormalizedBooking | None:
    if not bookings:
        return None
    checked_in = [
        booking for booking in bookings if booking.booking_status == BookingStatus.CHECKED_IN
    ]
    if checked_in:
        return sorted(checked_in, key=lambda item: checkout_at(item, policy))[0]
    expected = [booking for booking in bookings if booking.booking_status == BookingStatus.EXPECTED]
    if expected:
        return sorted(expected, key=lambda item: arrival_at(item, policy))[0]
    return sorted(bookings, key=lambda item: item.arrival_date)[0]
