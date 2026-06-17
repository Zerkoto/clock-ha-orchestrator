from __future__ import annotations

import ssl
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from threading import Event
from typing import Any

import paho.mqtt.client as mqtt

from app.settings import Settings

MessageHandler = Callable[[str, bytes], None]


class ManagedMqttClient:
    def __init__(
        self,
        settings: Settings,
        *,
        on_connect: Callable[[], None] | None = None,
    ) -> None:
        self._settings = settings
        self._on_connected = on_connect
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=settings.mqtt_client_id,
            protocol=mqtt.MQTTv5,
        )
        self._connected = False
        self._connect_event = Event()
        self._disconnect_event = Event()
        self._connect_error: str | None = None
        self._handlers: dict[str, MessageHandler] = {}
        self._executor = ThreadPoolExecutor(max_workers=settings.mqtt_callback_workers)
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
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        self._connect_event.clear()
        self._disconnect_event.clear()
        self._connect_error = None
        self._client.connect(self._settings.mqtt_host, self._settings.mqtt_port, keepalive=60)
        self._client.loop_start()
        if not self._connect_event.wait(self._settings.mqtt_connect_timeout_seconds):
            self._client.loop_stop()
            raise TimeoutError("MQTT connection timed out")
        if not self._connected:
            self._client.loop_stop()
            raise ConnectionError(self._connect_error or "MQTT connection failed")

    def disconnect(self) -> None:
        if self._connected:
            receipt = self.publish(
                f"{self._settings.mqtt_topic_prefix}/system/clock-ha-orchestrator/availability",
                "offline",
                qos=1,
                retain=True,
            )
            _wait_for_receipt(
                receipt,
                timeout_seconds=self._settings.mqtt_publish_timeout_seconds,
            )
        self._client.disconnect()
        self._disconnect_event.wait(self._settings.mqtt_connect_timeout_seconds)
        self._client.loop_stop()
        self._executor.shutdown(wait=False, cancel_futures=True)

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
        if self._connected:
            self._client.subscribe(topic, qos=1)

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        del userdata, flags, properties
        self._connected = not reason_code.is_failure
        if self._connected:
            self._connect_error = None
            for topic in self._handlers:
                client.subscribe(topic, qos=1)
            if self._on_connected is not None:
                self._executor.submit(_safe_call, self._on_connected)
        else:
            self._connect_error = str(reason_code)
        self._connect_event.set()

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
        self._disconnect_event.set()

    def _on_message(
        self,
        client: mqtt.Client,
        userdata: Any,
        message: mqtt.MQTTMessage,
    ) -> None:
        del client, userdata
        for topic, handler in self._handlers.items():
            if mqtt.topic_matches_sub(topic, message.topic):
                self._executor.submit(_safe_call, handler, message.topic, bytes(message.payload))


def _wait_for_receipt(receipt: Any, *, timeout_seconds: int) -> None:
    wait = getattr(receipt, "wait_for_publish", None)
    if callable(wait):
        wait(timeout=timeout_seconds)


def _safe_call(callback: Callable[..., None], *args: Any) -> None:
    with suppress(Exception):
        callback(*args)
