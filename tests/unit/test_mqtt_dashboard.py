from app.dashboard.generator import generate_dashboard
from app.domain.models import Entrance, PropertyRegistry, Room, RoomRegistry
from app.mqtt.discovery import (
    entrance_discovery_configs,
    room_discovery_configs,
    system_discovery_configs,
)
from app.mqtt.topics import MqttTopics


def test_topics_match_contract() -> None:
    topics = MqttTopics("hotel/v1")

    assert topics.availability == "hotel/v1/system/clock-ha-orchestrator/availability"
    assert topics.room_control_set("214") == "hotel/v1/rooms/214/control/set"
    assert topics.room_control_mode_set("214") == "hotel/v1/rooms/214/control/mode/set"
    assert (
        topics.room_control_return_to_automatic_set("214")
        == "hotel/v1/rooms/214/control/return-to-automatic/set"
    )
    assert topics.room_reported_state("214") == "hotel/v1/rooms/214/reported/state"
    assert topics.room_intent_result("214") == "hotel/v1/rooms/214/intent/result"
    assert (
        topics.entrance_adapter_state("entrance_a") == "hotel/v1/entrances/entrance_a/adapter/state"
    )


def test_discovery_uses_stable_unique_ids() -> None:
    room = Room(key="214", name="Apartment 214", entrance_key="entrance_a", floor="2")

    configs = dict(room_discovery_configs(room, MqttTopics()))

    assert "homeassistant/sensor/room_214_pms_status/config" in configs
    assert configs["homeassistant/sensor/room_214_pms_status/config"]["unique_id"] == (
        "clock_room_214_pms_status"
    )
    control_mode = configs["homeassistant/select/room_214_control_mode/config"]
    assert control_mode["command_topic"] == "hotel/v1/rooms/214/control/mode/set"
    assert control_mode["state_topic"] == "hotel/v1/rooms/214/control/state"
    assert control_mode["availability_topic"] == (
        "hotel/v1/system/clock-ha-orchestrator/availability"
    )
    hvac_mode = configs["homeassistant/select/room_214_manual_hvac_mode/config"]
    assert hvac_mode["state_topic"] == "hotel/v1/rooms/214/control/state"
    assert hvac_mode["command_topic"] == "hotel/v1/rooms/214/control/hvac-mode/set"
    temperature = configs["homeassistant/number/room_214_manual_temperature/config"]
    assert temperature["unit_of_measurement"] == "°C"
    water_heater = configs["homeassistant/switch/room_214_manual_water_heater/config"]
    assert water_heater["value_template"] == (
        "{{ 'on' if value_json.manual_water_heater_enabled else 'off' }}"
    )
    reported_temperature = configs["homeassistant/sensor/room_214_reported_temperature/config"]
    assert reported_temperature["state_topic"] == "hotel/v1/rooms/214/reported/state"
    reported_online = configs["homeassistant/binary_sensor/room_214_reported_online/config"]
    assert reported_online["state_topic"] == "hotel/v1/rooms/214/reported/state"
    assert "homeassistant/button/room_214_return_to_automatic/config" in configs


def test_entrance_discovery_contains_gateway_and_adapter_health() -> None:
    configs = dict(
        entrance_discovery_configs(
            [Entrance(key="entrance_a", name="Entrance A")],
            MqttTopics(),
        )
    )

    adapter = configs["homeassistant/binary_sensor/entrance_entrance_a_adapter_online/config"]
    assert adapter["state_topic"] == "hotel/v1/entrances/entrance_a/adapter/state"
    assert adapter["availability_topic"] == ("hotel/v1/entrances/entrance_a/adapter/availability")
    assert "homeassistant/sensor/entrance_entrance_a_room_mismatches/config" in configs
    latency = configs["homeassistant/sensor/entrance_entrance_a_gateway_latency/config"]
    assert latency["unit_of_measurement"] == "ms"
    assert "homeassistant/sensor/entrance_entrance_a_command_queue_depth/config" in configs


def test_system_discovery_contains_online_sensor() -> None:
    configs = dict(system_discovery_configs(MqttTopics()))

    assert "homeassistant/binary_sensor/clock_ha_orchestrator_online/config" in configs
    assert "homeassistant/binary_sensor/clock_runtime_ready/config" in configs
    assert "homeassistant/sensor/hotel_active_manual_overrides/config" in configs
    assert "homeassistant/sensor/clock_orchestrator_status/config" in configs


def test_dashboard_has_entrance_view_from_registry() -> None:
    registry = RoomRegistry(
        property=PropertyRegistry(key="local_stay_razlog", name="Local Stay Hotel & Suites"),
        entrances=[Entrance(key="entrance_a", name="Entrance A")],
        rooms=[Room(key="214", name="Apartment 214", entrance_key="entrance_a", floor="2")],
    )

    dashboard = generate_dashboard(registry)

    assert any(view["title"] == "Entrance A" for view in dashboard["views"])
    assert any(view["title"] == "Manual" for view in dashboard["views"])
    assert dashboard["views"][0]["type"] == "sections"
    assert "cards" not in dashboard["views"][0]
    assert dashboard["views"][0]["sections"][0]["type"] == "grid"
    overview_cards = dashboard["views"][0]["sections"][0]["cards"]
    assert {"type": "tile", "entity": "sensor.hotel_arrivals_today", "name": "Arrivals"} in (
        overview_cards
    )
    assert any(
        card.get("entity") == "sensor.hotel_active_manual_overrides"
        for card in _flatten_cards(dashboard)
    )
    assert any(card.get("title") == "Gateway and Adapter" for card in _flatten_cards(dashboard))


def _flatten_cards(dashboard):
    for view in dashboard["views"]:
        for section in view["sections"]:
            for card in section["cards"]:
                if card["type"] == "conditional":
                    yield card["card"]
                else:
                    yield card
