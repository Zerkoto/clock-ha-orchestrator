from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.domain.models import Room
from app.mqtt.topics import MqttTopics


def discovery_topic(component: str, object_id: str) -> str:
    return f"homeassistant/{component}/{object_id}/config"


def room_device(room: Room) -> dict[str, Any]:
    return {
        "identifiers": [f"clock_room_{room.key}"],
        "name": room.name,
        "manufacturer": "Clock PMS+ / Home Assistant Orchestrator",
        "model": "Hotel Room Automation Intent",
    }


def room_discovery_configs(room: Room, topics: MqttTopics) -> Iterable[tuple[str, dict[str, Any]]]:
    device = room_device(room)
    state_topic = topics.room_pms_state(room.key)
    intent_topic = topics.room_intent_state(room.key)
    control_state_topic = topics.room_control_state(room.key)
    base = f"room_{room.key}"
    availability = {
        "availability_topic": topics.availability,
        "payload_available": "online",
        "payload_not_available": "offline",
    }

    sensors = {
        "pms_status": ("PMS Status", state_topic, "{{ value_json.booking_status }}"),
        "automation_phase": ("Automation Phase", state_topic, "{{ value_json.automation_phase }}"),
        "arrival": ("Arrival", state_topic, "{{ value_json.arrival }}"),
        "departure": ("Departure", state_topic, "{{ value_json.departure }}"),
        "desired_hvac_mode": ("Desired HVAC Mode", intent_topic, "{{ value_json.hvac.mode }}"),
        "desired_temperature": (
            "Desired Temperature",
            intent_topic,
            "{{ value_json.hvac.target_temperature_c }}",
        ),
        "desired_water_heater": (
            "Desired Water Heater",
            intent_topic,
            "{{ value_json.water_heater.enabled }}",
        ),
    }
    for suffix, (name, topic, template) in sensors.items():
        object_id = f"{base}_{suffix}"
        yield (
            discovery_topic("sensor", object_id),
            {
                "name": name,
                "object_id": object_id,
                "unique_id": f"clock_{object_id}",
                "state_topic": topic,
                "value_template": template,
                "device": device,
                **availability,
            },
        )

    binary_sensors = {
        "reservation_active": "{{ value_json.booking_status in ['expected', 'checked_in'] }}",
        "needs_attention": "{{ value_json.needs_attention }}",
    }
    for suffix, template in binary_sensors.items():
        object_id = f"{base}_{suffix}"
        yield (
            discovery_topic("binary_sensor", object_id),
            {
                "name": suffix.replace("_", " ").title(),
                "object_id": object_id,
                "unique_id": f"clock_{object_id}",
                "state_topic": state_topic,
                "value_template": template,
                "payload_on": "True",
                "payload_off": "False",
                "device": device,
                **availability,
            },
        )

    yield (
        discovery_topic("select", f"{base}_control_mode"),
        {
            "name": "Control Mode",
            "object_id": f"{base}_control_mode",
            "unique_id": f"clock_{base}_control_mode",
            "state_topic": control_state_topic,
            "value_template": "{{ value_json.control_mode }}",
            "command_topic": topics.room_control_mode_set(room.key),
            "options": ["automatic", "manual", "off"],
            "device": device,
            **availability,
        },
    )
    yield (
        discovery_topic("select", f"{base}_manual_hvac_mode"),
        {
            "name": "Manual HVAC Mode",
            "object_id": f"{base}_manual_hvac_mode",
            "unique_id": f"clock_{base}_manual_hvac_mode",
            "state_topic": control_state_topic,
            "value_template": "{{ value_json.manual_hvac_mode }}",
            "command_topic": topics.room_control_hvac_mode_set(room.key),
            "options": ["off", "heat", "cool", "auto"],
            "device": device,
            **availability,
        },
    )
    yield (
        discovery_topic("number", f"{base}_manual_temperature"),
        {
            "name": "Manual Temperature",
            "object_id": f"{base}_manual_temperature",
            "unique_id": f"clock_{base}_manual_temperature",
            "state_topic": control_state_topic,
            "value_template": "{{ value_json.manual_target_temperature_c }}",
            "command_topic": topics.room_control_temperature_set(room.key),
            "min": 16,
            "max": 28,
            "step": 0.5,
            "unit_of_measurement": "°C",
            "device": device,
            **availability,
        },
    )
    yield (
        discovery_topic("select", f"{base}_override_duration"),
        {
            "name": "Override Duration",
            "object_id": f"{base}_override_duration",
            "unique_id": f"clock_{base}_override_duration",
            "state_topic": control_state_topic,
            "value_template": "{{ value_json.override_duration }}",
            "command_topic": topics.room_control_duration_set(room.key),
            "options": ["60", "240", "720", "until_checkout"],
            "device": device,
            **availability,
        },
    )
    yield (
        discovery_topic("switch", f"{base}_manual_water_heater"),
        {
            "name": "Manual Water Heater",
            "object_id": f"{base}_manual_water_heater",
            "unique_id": f"clock_{base}_manual_water_heater",
            "state_topic": control_state_topic,
            "value_template": "{{ 'on' if value_json.manual_water_heater_enabled else 'off' }}",
            "command_topic": topics.room_control_water_heater_set(room.key),
            "payload_on": "on",
            "payload_off": "off",
            "device": device,
            **availability,
        },
    )
    yield (
        discovery_topic("button", f"{base}_return_to_automatic"),
        {
            "name": "Return To Automatic",
            "object_id": f"{base}_return_to_automatic",
            "unique_id": f"clock_{base}_return_to_automatic",
            "command_topic": topics.room_control_return_to_automatic_set(room.key),
            "payload_press": "return",
            "device": device,
            **availability,
        },
    )


def system_discovery_configs(topics: MqttTopics) -> Iterable[tuple[str, dict[str, Any]]]:
    device = {
        "identifiers": ["clock_ha_orchestrator"],
        "name": "Clock HA Orchestrator",
        "manufacturer": "Clock PMS+ / Home Assistant Orchestrator",
    }
    sensors = {
        "clock_last_successful_sync": ("Last Successful Sync", "{{ value_json.last_success_at }}"),
        "clock_sync_lag": ("Clock Sync Lag", "{{ value_json.lag_seconds }}"),
        "hotel_checked_in_rooms": ("Checked In Rooms", "{{ value_json.checked_in_rooms }}"),
        "hotel_expected_rooms": ("Expected Rooms", "{{ value_json.expected_rooms }}"),
        "hotel_arrivals_today": ("Arrivals Today", "{{ value_json.arrivals_today }}"),
        "hotel_departures_today": ("Departures Today", "{{ value_json.departures_today }}"),
        "hotel_unassigned_arrivals": (
            "Unassigned Arrivals",
            "{{ value_json.unassigned_arrivals }}",
        ),
        "hotel_room_conflicts": ("Room Conflicts", "{{ value_json.room_conflicts }}"),
    }
    yield (
        discovery_topic("binary_sensor", "clock_ha_orchestrator_online"),
        {
            "name": "Clock HA Orchestrator Online",
            "object_id": "clock_ha_orchestrator_online",
            "unique_id": "clock_ha_orchestrator_online",
            "state_topic": topics.availability,
            "payload_on": "online",
            "payload_off": "offline",
            "device": device,
        },
    )
    for object_id, (name, template) in sensors.items():
        yield (
            discovery_topic("sensor", object_id),
            {
                "name": name,
                "object_id": object_id,
                "unique_id": f"clock_{object_id}",
                "state_topic": topics.system_state,
                "value_template": template,
                "device": device,
                "availability_topic": topics.availability,
                "payload_available": "online",
                "payload_not_available": "offline",
            },
        )
