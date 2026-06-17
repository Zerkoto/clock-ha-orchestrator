from __future__ import annotations

import ssl
from collections.abc import Callable
from typing import Any

import paho.mqtt.client as mqtt

from app.settings import Settings

MessageHandler = Callable[[str, bytes], None]


class ManagedMqttClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=settings.mqtt_client_id,
            protocol=mqtt.MQTTv5,
        )
        self._connected = False
        self._handlers: dict[str, MessageHandler] = {}
        if settings.mqtt_username:
            self._client.username_pw_set(
                settings.mqtt_username,
                settings.mqtt_password.get_secret_value() if settings.mqtt_password else None,
            )
        if settings.mqtt_tls:
            self._client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
        self._client.will_set(
            f"{settings.mqtt_topic_prefix}/system/clock-ha-orchestrator/availability",
            payload="offline",
            qos=1,
            retain=True,
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        self._client.connect(self._settings.mqtt_host, self._settings.mqtt_port, keepalive=60)
        self._client.loop_start()

    def disconnect(self) -> None:
        self.publish(
            f"{self._settings.mqtt_topic_prefix}/system/clock-ha-orchestrator/availability",
            "offline",
            qos=1,
            retain=True,
        )
        self._client.loop_stop()
        self._client.disconnect()

    def publish(
        self,
        topic: str,
        payload: str | bytes,
        *,
        qos: int = 1,
        retain: bool = True,
    ) -> Any:
        return self._client.publish(topic, payload=payload, qos=qos, retain=retain)

    def subscribe(self, topic: str, handler: MessageHandler) -> None:
        self._handlers[topic] = handler
        self._client.subscribe(topic, qos=1)

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        del client, userdata, flags, properties
        self._connected = not reason_code.is_failure

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: mqtt.DisconnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        del client, userdata, flags, reason_code, properties
        self._connected = False

    def _on_message(
        self,
        client: mqtt.Client,
        userdata: Any,
        message: mqtt.MQTTMessage,
    ) -> None:
        del client, userdata
        for topic, handler in self._handlers.items():
            if mqtt.topic_matches_sub(topic, message.topic):
                handler(message.topic, bytes(message.payload))
