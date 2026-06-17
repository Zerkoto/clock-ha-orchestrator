from __future__ import annotations

import json
from typing import Any, Protocol

from pydantic import BaseModel


class MqttPublisher(Protocol):
    def publish(
        self,
        topic: str,
        payload: str | bytes,
        *,
        qos: int = 1,
        retain: bool = True,
    ) -> Any:
        """Publish a payload to MQTT."""


def serialize_payload(payload: BaseModel | dict[str, Any] | str) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, BaseModel):
        return payload.model_dump_json()
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
