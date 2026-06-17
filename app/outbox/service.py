from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.mqtt.publisher import MqttPublisher, serialize_payload


@dataclass
class PendingOutboxMessage:
    id: UUID
    topic: str
    payload: dict[str, Any]
    qos: int = 1
    retain: bool = True
    attempts: int = 0


@dataclass(frozen=True)
class OutboxPublishResult:
    message_id: UUID
    published: bool
    published_at: datetime | None
    error: str | None = None


class OutboxPublisher:
    def __init__(self, publisher: MqttPublisher) -> None:
        self._publisher = publisher

    def publish_pending(self, messages: list[PendingOutboxMessage]) -> list[OutboxPublishResult]:
        results: list[OutboxPublishResult] = []
        for message in messages:
            try:
                self._publisher.publish(
                    message.topic,
                    serialize_payload(message.payload),
                    qos=message.qos,
                    retain=message.retain,
                )
                results.append(
                    OutboxPublishResult(
                        message_id=message.id,
                        published=True,
                        published_at=datetime.now(UTC),
                    )
                )
            except Exception as exc:
                results.append(
                    OutboxPublishResult(
                        message_id=message.id,
                        published=False,
                        published_at=None,
                        error=exc.__class__.__name__,
                    )
                )
        return results

