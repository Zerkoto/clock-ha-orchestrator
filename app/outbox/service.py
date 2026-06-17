from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from random import Random
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.mqtt.publisher import MqttPublisher, serialize_payload
from app.persistence import models as db


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


@dataclass(frozen=True)
class OutboxRetryPolicy:
    max_attempts: int = 8
    base_delay_seconds: int = 5
    max_delay_seconds: int = 300
    jitter_seconds: int = 5


class OutboxPublisher:
    def __init__(self, publisher: MqttPublisher) -> None:
        self._publisher = publisher

    def publish_pending(self, messages: list[PendingOutboxMessage]) -> list[OutboxPublishResult]:
        results: list[OutboxPublishResult] = []
        for message in messages:
            try:
                receipt = self._publisher.publish(
                    message.topic,
                    serialize_payload(message.payload),
                    qos=message.qos,
                    retain=message.retain,
                )
                _wait_for_publish_ack(receipt)
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


class OutboxStore:
    def __init__(self, session: Session, retry_policy: OutboxRetryPolicy | None = None) -> None:
        self._session = session
        self._retry_policy = retry_policy or OutboxRetryPolicy()
        self._random = Random()

    def claim_pending(
        self,
        *,
        worker_id: str,
        now: datetime,
        limit: int,
    ) -> list[PendingOutboxMessage]:
        claimable = self._session.execute(
            select(db.OutboxEvent)
            .where(
                db.OutboxEvent.status.in_(("pending", "retrying")),
                or_(
                    db.OutboxEvent.next_attempt_at.is_(None),
                    db.OutboxEvent.next_attempt_at <= now,
                ),
            )
            .order_by(db.OutboxEvent.created_at, db.OutboxEvent.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).scalars()
        rows = list(claimable)
        for row in rows:
            row.status = "publishing"
            row.claimed_at = now
            row.claimed_by = worker_id
        self._session.flush()
        return [
            PendingOutboxMessage(
                id=row.id,
                topic=row.topic,
                payload=row.payload,
                qos=row.qos,
                retain=row.retain,
                attempts=row.attempts,
            )
            for row in rows
        ]

    def record_results(
        self,
        results: list[OutboxPublishResult],
        *,
        now: datetime,
    ) -> None:
        for result in results:
            row = self._session.get(db.OutboxEvent, result.message_id)
            if row is None:
                continue
            row.claimed_at = None
            row.claimed_by = None
            if result.published:
                row.status = "published"
                row.published_at = result.published_at or now
                row.last_error = None
                row.next_attempt_at = None
                continue

            row.attempts += 1
            row.last_error = result.error
            if row.attempts >= self._retry_policy.max_attempts:
                row.status = "dead_letter"
                row.next_attempt_at = None
            else:
                row.status = "retrying"
                row.next_attempt_at = now + self._retry_delay(row.attempts)
        self._session.flush()

    def release_stale_publishing(
        self,
        *,
        now: datetime,
        older_than: timedelta,
    ) -> int:
        stale = self._session.execute(
            select(db.OutboxEvent).where(
                db.OutboxEvent.status == "publishing",
                db.OutboxEvent.claimed_at < now - older_than,
            )
        ).scalars()
        rows = list(stale)
        for row in rows:
            row.status = "retrying"
            row.claimed_at = None
            row.claimed_by = None
            row.next_attempt_at = now
        self._session.flush()
        return len(rows)

    def retry_dead_letters(self, *, now: datetime) -> int:
        dead_letters = self._session.execute(
            select(db.OutboxEvent).where(db.OutboxEvent.status == "dead_letter")
        ).scalars()
        rows = list(dead_letters)
        for row in rows:
            row.status = "retrying"
            row.next_attempt_at = now
            row.last_error = None
            row.claimed_at = None
            row.claimed_by = None
        self._session.flush()
        return len(rows)

    def _retry_delay(self, attempts: int) -> timedelta:
        exponential = self._retry_policy.base_delay_seconds * (2 ** max(attempts - 1, 0))
        capped = min(exponential, self._retry_policy.max_delay_seconds)
        jitter = (
            self._random.uniform(0, self._retry_policy.jitter_seconds)
            if self._retry_policy.jitter_seconds > 0
            else 0
        )
        return timedelta(seconds=capped + jitter)


def _wait_for_publish_ack(receipt: Any) -> None:
    if receipt is None:
        return
    wait = getattr(receipt, "wait_for_publish", None)
    if callable(wait):
        wait()
    is_published = getattr(receipt, "is_published", None)
    if callable(is_published) and not is_published():
        raise RuntimeError("MQTT publish was not acknowledged")
