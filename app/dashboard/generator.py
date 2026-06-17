from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.domain.models import RoomRegistry


def generate_dashboard(registry: RoomRegistry) -> dict[str, Any]:
    views: list[dict[str, Any]] = [
        _overview_view(),
        _arrivals_view(),
        _departures_view(),
        _alerts_view(),
        _integration_view(),
    ]
    floors: dict[str, list[str]] = defaultdict(list)
    for room in sorted(registry.rooms, key=lambda item: (item.floor, item.key)):
        floors[room.floor].append(room.key)
    for floor, room_keys in floors.items():
        views.append(_floor_view(floor, room_keys))
    return {
        "title": f"{registry.property.name} Reception",
        "views": views,
    }


def _overview_view() -> dict[str, Any]:
    return _sections_view(
        "Overview",
        [
            {
                "type": "heading",
                "heading": "Clock Integration",
                "badges": [
                    {"type": "entity", "entity": "binary_sensor.clock_ha_orchestrator_online"},
                    {"type": "entity", "entity": "sensor.clock_last_successful_sync"},
                    {"type": "entity", "entity": "sensor.clock_sync_lag"},
                ],
            },
            {
                "type": "tile",
                "entity": "sensor.hotel_checked_in_rooms",
                "name": "Checked In",
            },
            {"type": "tile", "entity": "sensor.hotel_expected_rooms", "name": "Expected"},
            {"type": "tile", "entity": "sensor.hotel_arrivals_today", "name": "Arrivals"},
            {"type": "tile", "entity": "sensor.hotel_departures_today", "name": "Departures"},
            {
                "type": "conditional",
                "conditions": [{"entity": "sensor.hotel_room_conflicts", "state_not": "0"}],
                "card": {"type": "tile", "entity": "sensor.hotel_room_conflicts", "color": "red"},
            },
        ],
    )


def _arrivals_view() -> dict[str, Any]:
    return _sections_view(
        "Arrivals",
        [
            {"type": "heading", "heading": "Today"},
            {
                "type": "entities",
                "entities": [
                    "sensor.hotel_arrivals_today",
                    "sensor.hotel_unassigned_arrivals",
                ],
            },
        ],
    )


def _departures_view() -> dict[str, Any]:
    return _sections_view(
        "Departures",
        [
            {"type": "heading", "heading": "Today"},
            {"type": "entities", "entities": ["sensor.hotel_departures_today"]},
        ],
    )


def _alerts_view() -> dict[str, Any]:
    return _sections_view(
        "Alerts",
        [
            {"type": "heading", "heading": "Needs Attention"},
            {
                "type": "entities",
                "entities": [
                    "sensor.hotel_unassigned_arrivals",
                    "sensor.hotel_room_conflicts",
                    "sensor.clock_sync_lag",
                ],
            },
        ],
    )


def _integration_view() -> dict[str, Any]:
    return _sections_view(
        "Integration",
        [
            {"type": "heading", "heading": "Orchestrator"},
            {
                "type": "entities",
                "entities": [
                    "binary_sensor.clock_ha_orchestrator_online",
                    "sensor.clock_last_successful_sync",
                    "sensor.clock_sync_lag",
                ],
            },
        ],
    )


def _floor_view(floor: str, room_keys: list[str]) -> dict[str, Any]:
    cards: list[dict[str, Any]] = [{"type": "heading", "heading": f"Floor {floor}"}]
    for room_key in room_keys:
        cards.append(_room_card(room_key))
    return _sections_view(f"Floor {floor}", cards)


def _room_card(room_key: str) -> dict[str, Any]:
    prefix = f"room_{room_key}"
    return {
        "type": "entities",
        "title": f"Room {room_key}",
        "entities": [
            f"sensor.{prefix}_pms_status",
            f"sensor.{prefix}_automation_phase",
            f"sensor.{prefix}_arrival",
            f"sensor.{prefix}_departure",
            f"sensor.{prefix}_desired_hvac_mode",
            f"sensor.{prefix}_desired_temperature",
            f"sensor.{prefix}_desired_water_heater",
            f"select.{prefix}_control_mode",
            f"select.{prefix}_manual_hvac_mode",
            f"number.{prefix}_manual_temperature",
            f"select.{prefix}_override_duration",
            f"switch.{prefix}_manual_water_heater",
            f"button.{prefix}_return_to_automatic",
            f"binary_sensor.{prefix}_needs_attention",
        ],
    }


def _sections_view(title: str, cards: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "title": title,
        "type": "sections",
        "sections": [
            {
                "type": "grid",
                "cards": cards,
            }
        ],
    }
