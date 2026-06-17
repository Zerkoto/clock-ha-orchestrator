from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.outbox.service import (
    OutboxPublisher,
    OutboxPublishResult,
    OutboxRetryPolicy,
    OutboxStore,
    PendingOutboxMessage,
)
from app.persistence import models as db

NOW = datetime(2026, 6, 17, 10, 0, tzinfo=UTC)
CORRELATION_ID = UUID("00000000-0000-0000-0000-000000000222")


def build_engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db.Base.metadata.create_all(engine)
    return engine


def test_outbox_claim_marks_rows_as_publishing() -> None:
    engine = build_engine()
    with Session(engine) as session, session.begin():
        event = add_event(session)
        store = OutboxStore(session)
        messages = store.claim_pending(worker_id="worker-1", now=NOW, limit=10)

        assert [message.id for message in messages] == [event.id]
        assert event.status == "publishing"
        assert event.claimed_by == "worker-1"


def test_outbox_failure_retries_then_dead_letters() -> None:
    engine = build_engine()
    policy = OutboxRetryPolicy(
        max_attempts=2,
        base_delay_seconds=10,
        max_delay_seconds=30,
        jitter_seconds=0,
    )
    with Session(engine) as session, session.begin():
        event = add_event(session)
        store = OutboxStore(session, policy)
        store.claim_pending(worker_id="worker-1", now=NOW, limit=10)
        store.record_results(
            [
                OutboxPublishResult(
                    message_id=event.id,
                    published=False,
                    published_at=None,
                    error="MqttUnavailable",
                )
            ],
            now=NOW,
        )

        assert event.status == "retrying"
        assert event.attempts == 1
        assert event.next_attempt_at == NOW + timedelta(seconds=10)

        store.claim_pending(worker_id="worker-1", now=NOW + timedelta(seconds=10), limit=10)
        store.record_results(
            [
                OutboxPublishResult(
                    message_id=event.id,
                    published=False,
                    published_at=None,
                    error="MqttUnavailable",
                )
            ],
            now=NOW + timedelta(seconds=10),
        )

        assert event.status == "dead_letter"
        assert event.attempts == 2
        assert event.next_attempt_at is None


def test_outbox_success_marks_published_after_claim() -> None:
    engine = build_engine()
    with Session(engine) as session, session.begin():
        event = add_event(session)
        store = OutboxStore(session)
        store.claim_pending(worker_id="worker-1", now=NOW, limit=10)
        store.record_results(
            [
                OutboxPublishResult(
                    message_id=event.id,
                    published=True,
                    published_at=NOW,
                )
            ],
            now=NOW,
        )

        assert event.status == "published"
        assert event.published_at == NOW
        assert event.claimed_by is None


def test_retry_dead_letters_makes_rows_claimable_again() -> None:
    engine = build_engine()
    with Session(engine) as session, session.begin():
        event = add_event(session, status="dead_letter", next_attempt_at=None)
        event.last_error = "MqttUnavailable"
        store = OutboxStore(session)

        count = store.retry_dead_letters(now=NOW)

        assert count == 1
        assert event.status == "retrying"
        assert event.next_attempt_at == NOW
        assert event.last_error is None


def test_outbox_publisher_marks_unacknowledged_publish_as_failed() -> None:
    publisher = OutboxPublisher(
        FakePublisher(FakeReceipt(published=False)),
        publish_timeout_seconds=1,
    )

    result = publisher.publish_pending(
        [
            PendingOutboxMessage(
                id=CORRELATION_ID,
                topic="hotel/v1/test",
                payload={"schema_version": 1},
            )
        ]
    )

    assert result[0].published is False
    assert result[0].error == "RuntimeError"


def add_event(
    session: Session,
    *,
    status: str = "pending",
    next_attempt_at: datetime | None = NOW,
) -> db.OutboxEvent:
    event = db.OutboxEvent(
        topic="hotel/v1/test",
        payload={"schema_version": 1},
        qos=1,
        retain=True,
        status=status,
        attempts=0,
        next_attempt_at=next_attempt_at,
        created_at=NOW,
        correlation_id=CORRELATION_ID,
    )
    session.add(event)
    session.flush()
    return event


class FakeReceipt:
    def __init__(self, *, published: bool) -> None:
        self._published = published
        self.timeout: int | None = None

    def wait_for_publish(self, timeout: int | None = None) -> None:
        self.timeout = timeout

    def is_published(self) -> bool:
        return self._published


class FakePublisher:
    def __init__(self, receipt: FakeReceipt) -> None:
        self._receipt = receipt

    def publish(self, topic: str, payload: str | bytes, *, qos: int, retain: bool):
        del topic, payload, qos, retain
        return self._receipt
