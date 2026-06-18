from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.domain.models import Entrance, Room
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
    reported_topic = topics.room_reported_state(room.key)
    result_topic = topics.room_intent_result(room.key)
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
        "reported_hvac_mode": ("Reported HVAC Mode", reported_topic, "{{ value_json.hvac.mode }}"),
        "reported_temperature": (
            "Reported Temperature",
            reported_topic,
            "{{ value_json.ambient_temperature_c }}",
        ),
        "reported_faults": (
            "Reported Faults",
            reported_topic,
            "{{ value_json.faults | count }}",
        ),
        "reported_at": ("Reported At", reported_topic, "{{ value_json.reported_at }}"),
        "last_intent_result": ("Last Intent Result", result_topic, "{{ value_json.status }}"),
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
        "reported_online": "{{ value_json.online }}",
    }
    for suffix, template in binary_sensors.items():
        binary_state_topic = reported_topic if suffix == "reported_online" else state_topic
        object_id = f"{base}_{suffix}"
        yield (
            discovery_topic("binary_sensor", object_id),
            {
                "name": suffix.replace("_", " ").title(),
                "object_id": object_id,
                "unique_id": f"clock_{object_id}",
                "state_topic": binary_state_topic,
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


def entrance_discovery_configs(
    entrances: Iterable[Entrance],
    topics: MqttTopics,
) -> Iterable[tuple[str, dict[str, Any]]]:
    for entrance in entrances:
        object_prefix = f"entrance_{entrance.key.replace('-', '_')}"
        state_topic = topics.entrance_adapter_state(entrance.key)
        availability_topic = topics.entrance_adapter_availability(entrance.key)
        device = {
            "identifiers": [f"clock_entrance_{entrance.key}"],
            "name": entrance.name,
            "manufacturer": "Clock HA Orchestrator",
            "model": "G301 Entrance Adapter",
        }
        availability = {
            "availability_topic": availability_topic,
            "payload_available": "online",
            "payload_not_available": "offline",
        }
        sensors = {
            "adapter_status": ("Adapter Status", "{{ value_json.status }}"),
            "last_poll": ("Last Poll", "{{ value_json.last_poll_at }}"),
            "last_successful_poll": (
                "Last Successful Poll",
                "{{ value_json.last_successful_poll_at }}",
            ),
            "room_mismatches": ("Room Mismatches", "{{ value_json.room_mismatches }}"),
            "gateway_latency": ("Gateway Latency", "{{ value_json.gateway_latency_ms }}"),
            "consecutive_failures": (
                "Consecutive Failures",
                "{{ value_json.consecutive_failures }}",
            ),
            "online_slaves": ("Online Slaves", "{{ value_json.online_slaves }}"),
            "offline_slaves": ("Offline Slaves", "{{ value_json.offline_slaves }}"),
            "scan_duration": ("Scan Duration", "{{ value_json.scan_duration_ms }}"),
            "command_queue_depth": (
                "Command Queue Depth",
                "{{ value_json.command_queue_depth }}",
            ),
        }
        for suffix, (name, template) in sensors.items():
            object_id = f"{object_prefix}_{suffix}"
            config = {
                "name": name,
                "object_id": object_id,
                "unique_id": f"clock_{object_id}",
                "state_topic": state_topic,
                "value_template": template,
                "device": device,
                **availability,
            }
            if suffix in {"gateway_latency", "scan_duration"}:
                config["unit_of_measurement"] = "ms"
            yield (
                discovery_topic("sensor", object_id),
                config,
            )
        binary_sensors = {
            "adapter_online": "{{ value_json.adapter_online }}",
            "gateway_online": "{{ value_json.gateway_online }}",
        }
        for suffix, template in binary_sensors.items():
            object_id = f"{object_prefix}_{suffix}"
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


def system_discovery_configs(topics: MqttTopics) -> Iterable[tuple[str, dict[str, Any]]]:
    device = {
        "identifiers": ["clock_ha_orchestrator"],
        "name": "Clock HA Orchestrator",
        "manufacturer": "Clock PMS+ / Home Assistant Orchestrator",
    }
    sensors = {
        "clock_orchestrator_status": ("Orchestrator Status", "{{ value_json.status }}"),
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
        "hotel_active_manual_overrides": (
            "Active Manual Overrides",
            "{{ value_json.active_manual_overrides }}",
        ),
        "hotel_rooms_needing_attention": (
            "Rooms Needing Attention",
            "{{ value_json.rooms_needing_attention }}",
        ),
        "clock_pending_outbox": ("Pending Outbox", "{{ value_json.pending_outbox }}"),
        "clock_dead_letter_outbox": ("Dead Letter Outbox", "{{ value_json.dead_letter_outbox }}"),
    }
    binary_sensors = {
        "clock_ha_orchestrator_online": (
            "Clock HA Orchestrator Online",
            topics.availability,
            None,
            "online",
            "offline",
        ),
        "clock_runtime_ready": (
            "Clock Runtime Ready",
            topics.system_state,
            "{{ value_json.runtime_ready }}",
            "True",
            "False",
        ),
        "clock_mqtt_connected": (
            "Clock MQTT Connected",
            topics.system_state,
            "{{ value_json.mqtt_connected }}",
            "True",
            "False",
        ),
        "clock_policy_scheduler_enabled": (
            "Policy Scheduler Enabled",
            topics.system_state,
            "{{ value_json.policy_scheduler_enabled }}",
            "True",
            "False",
        ),
        "clock_outbox_worker_enabled": (
            "Outbox Worker Enabled",
            topics.system_state,
            "{{ value_json.outbox_worker_enabled }}",
            "True",
            "False",
        ),
    }
    for object_id, (name, state_topic, template, payload_on, payload_off) in binary_sensors.items():
        payload = {
            "name": name,
            "object_id": object_id,
            "unique_id": object_id,
            "state_topic": state_topic,
            "payload_on": payload_on,
            "payload_off": payload_off,
            "device": device,
        }
        if template is not None:
            payload["value_template"] = template
            payload["availability_topic"] = topics.availability
            payload["payload_available"] = "online"
            payload["payload_not_available"] = "offline"
        yield (discovery_topic("binary_sensor", object_id), payload)
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
