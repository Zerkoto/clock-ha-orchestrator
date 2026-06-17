from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.clock.db_sync import ClockDbSyncService
from app.clock.fixtures import FixtureClockClient
from app.clock.interface import ClockClient, ClockMappingRequired
from app.clock.normalizer import ClockFieldMapping
from app.clock.rest import ClockRestClient
from app.clock.sync import ClockSyncService
from app.config_loader import load_hotel_policy, load_room_registry, load_yaml_model
from app.domain.models import HotelPolicy, RoomRegistry
from app.mqtt.client import ManagedMqttClient
from app.mqtt.discovery import room_discovery_configs, system_discovery_configs
from app.mqtt.publisher import serialize_payload
from app.mqtt.topics import MqttTopics
from app.outbox.service import OutboxPublisher, OutboxRetryPolicy, OutboxStore
from app.policy.control import RoomControlCommandService
from app.settings import Settings
from app.system.state import build_system_state


@dataclass
class RuntimeHealth:
    database_connected: bool = False
    migration_current: bool = False
    mqtt_connected: bool = False
    workers_started: bool = False
    errors: list[str] = field(default_factory=list)
    worker_errors: dict[str, str] = field(default_factory=dict)
    requires_mqtt: bool = False

    @property
    def ready(self) -> bool:
        return (
            self.database_connected
            and self.migration_current
            and (self.mqtt_connected or not self.requires_mqtt)
            and not self.errors
            and not self.worker_errors
        )


class AppRuntime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.registry: RoomRegistry = load_room_registry(settings.room_registry_path)
        self.policy: HotelPolicy = load_hotel_policy(settings.policy_path)
        self.topics = MqttTopics(settings.mqtt_topic_prefix)
        self.engine: Engine = create_engine(settings.database_url, pool_pre_ping=True)
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
        )
        self.health = RuntimeHealth(requires_mqtt=settings.mqtt_enabled)
        self.mqtt_client: ManagedMqttClient | None = None
        self.clock_client: ClockClient | None = None
        self.clock_mapping: ClockFieldMapping | None = None
        self._sync_lock = asyncio.Lock()
        self._tasks: list[asyncio.Task[None]] = []
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        self._verify_database()
        self._verify_migration_head()
        self.clock_client, self.clock_mapping = self._build_clock_client()
        if self.settings.mqtt_enabled:
            self.mqtt_client = ManagedMqttClient(
                self.settings,
                on_connect=self._publish_mqtt_reconnect_state,
            )
            self.mqtt_client.connect()
            self.refresh_health()
            self.subscribe_home_assistant_commands()
            self.publish_availability("online")
            self.publish_discovery()
            self.publish_control_states()
            self.publish_system_state()
        self._start_background_tasks()
        self.health.workers_started = bool(self._tasks)

    async def stop(self) -> None:
        self._stopping.set()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        if self.mqtt_client is not None:
            self.mqtt_client.disconnect()
            self.refresh_health()
        self.engine.dispose()

    async def run_sync_once(self, *, now: datetime | None = None) -> dict[str, object]:
        if self.clock_client is None or self.clock_mapping is None:
            raise ClockMappingRequired("Clock client is not configured for synchronization")
        now = now or datetime.now(UTC)
        async with self._sync_lock:
            with self.session_factory() as session:
                cursor = ClockDbSyncService(
                    session=session,
                    room_registry=self.registry,
                    policy=self.policy,
                    topics=self.topics,
                ).load_cursor_state()
            sync_result = await ClockSyncService(
                client=self.clock_client,
                settings=self.settings,
                property_id=self.registry.property.key,
                mapping=self.clock_mapping,
            ).poll_once(cursor, now=now)
            with self.session_factory() as session:
                persisted = ClockDbSyncService(
                    session=session,
                    room_registry=self.registry,
                    policy=self.policy,
                    topics=self.topics,
                ).apply_sync_result(sync_result, correlation_id=uuid4())
            self.publish_system_state()
            return {
                "success": persisted.success,
                "processed_bookings": persisted.processed_bookings,
                "affected_room_keys": list(persisted.affected_room_keys),
                "room_states_created": persisted.room_states_created,
                "outbox_events_created": persisted.outbox_events_created,
                "audit_events_created": persisted.audit_events_created,
            }

    async def run_policy_once(self, *, now: datetime | None = None) -> dict[str, object]:
        now = now or datetime.now(UTC)
        with self.session_factory() as session:
            result = ClockDbSyncService(
                session=session,
                room_registry=self.registry,
                policy=self.policy,
                topics=self.topics,
            ).evaluate_all_rooms(now=now, correlation_id=uuid4())
        self.publish_system_state()
        return {
            "affected_room_keys": list(result.affected_room_keys),
            "room_states_created": result.room_states_created,
            "outbox_events_created": result.outbox_events_created,
        }

    async def run_outbox_once(self) -> int:
        if self.mqtt_client is None:
            return 0
        self.refresh_health()
        retry_policy = OutboxRetryPolicy(max_attempts=self.settings.outbox_max_attempts)
        with self.session_factory() as session, session.begin():
            store = OutboxStore(session, retry_policy)
            store.release_stale_publishing(
                now=datetime.now(UTC),
                older_than=timedelta(seconds=self.settings.outbox_stale_publish_seconds),
            )
        if not self.mqtt_client.connected:
            return 0
        now = datetime.now(UTC)
        worker_id = self.settings.mqtt_client_id
        with self.session_factory() as session, session.begin():
            store = OutboxStore(session, retry_policy)
            messages = store.claim_pending(
                worker_id=worker_id,
                now=now,
                limit=self.settings.outbox_batch_size,
            )
        results = OutboxPublisher(
            self.mqtt_client,
            publish_timeout_seconds=self.settings.mqtt_publish_timeout_seconds,
        ).publish_pending(messages)
        with self.session_factory() as session, session.begin():
            store = OutboxStore(session, retry_policy)
            store.record_results(results, now=datetime.now(UTC))
        self.publish_system_state()
        return len(messages)

    def refresh_health(self) -> None:
        self.health.mqtt_connected = (
            self.mqtt_client.connected if self.mqtt_client is not None else False
        )

    def _publish_mqtt_reconnect_state(self) -> None:
        self.refresh_health()
        self.publish_availability("online")
        self.publish_control_states()
        self.publish_system_state()

    def subscribe_home_assistant_commands(self) -> None:
        if self.mqtt_client is None:
            return
        for room in self.registry.rooms:
            subscriptions = {
                self.topics.room_control_mode_set(room.key): "mode",
                self.topics.room_control_hvac_mode_set(room.key): "hvac-mode",
                self.topics.room_control_temperature_set(room.key): "temperature",
                self.topics.room_control_duration_set(room.key): "duration",
                self.topics.room_control_water_heater_set(room.key): "water-heater",
                self.topics.room_control_return_to_automatic_set(room.key): ("return-to-automatic"),
            }
            for topic, command_field in subscriptions.items():
                self.mqtt_client.subscribe(
                    topic,
                    self._control_handler(room.key, command_field),
                )

    def _control_handler(
        self,
        room_key: str,
        command_field: str,
    ) -> Callable[[str, bytes], None]:
        def handle(received_topic: str, payload: bytes) -> None:
            self.handle_control_message(
                room_key=room_key,
                field=command_field,
                topic=received_topic,
                payload=payload,
            )

        return handle

    def handle_control_message(
        self,
        *,
        room_key: str,
        field: str,
        topic: str,
        payload: bytes,
    ) -> None:
        del topic
        now = datetime.now(UTC)
        correlation_id = uuid4()
        try:
            with self.session_factory() as session, session.begin():
                result = RoomControlCommandService(
                    session=session,
                    room_registry=self.registry,
                    policy=self.policy,
                    topics=self.topics,
                ).apply_mqtt_command(
                    room_key=room_key,
                    field=field,
                    payload=payload,
                    now=now,
                    correlation_id=correlation_id,
                )
            if result.accepted and result.room_key is not None:
                with self.session_factory() as session:
                    ClockDbSyncService(
                        session=session,
                        room_registry=self.registry,
                        policy=self.policy,
                        topics=self.topics,
                    ).evaluate_room_keys(
                        room_keys={result.room_key},
                        now=now,
                        correlation_id=result.correlation_id,
                    )
            self.health.worker_errors.pop("mqtt-command", None)
        except Exception as exc:
            self.health.worker_errors["mqtt-command"] = exc.__class__.__name__
        self.publish_system_state()

    def publish_availability(self, status: str) -> None:
        self._publish_direct(self.topics.availability, status)

    def publish_discovery(self) -> None:
        if self.mqtt_client is None or not self.mqtt_client.connected:
            return
        for topic, payload in system_discovery_configs(self.topics):
            self._publish_direct(topic, serialize_payload(payload))
        for room in self.registry.rooms:
            for topic, payload in room_discovery_configs(room, self.topics):
                self._publish_direct(topic, serialize_payload(payload))

    def publish_system_state(self) -> None:
        if self.mqtt_client is None or not self.mqtt_client.connected:
            return
        self.refresh_health()
        with self.session_factory() as session:
            payload = self.system_state(session)
        self._publish_direct(
            self.topics.system_state,
            serialize_payload(payload),
        )

    def publish_control_states(self) -> None:
        if self.mqtt_client is None or not self.mqtt_client.connected:
            return
        now = datetime.now(UTC)
        with self.session_factory() as session:
            service = RoomControlCommandService(
                session=session,
                room_registry=self.registry,
                policy=self.policy,
                topics=self.topics,
            )
            payloads = [
                (
                    self.topics.room_control_state(room.key),
                    service.control_state_payload(room_key=room.key, now=now),
                )
                for room in self.registry.rooms
            ]
        for topic, payload in payloads:
            self._publish_direct(topic, serialize_payload(payload))

    def _publish_direct(self, topic: str, payload: str | bytes) -> bool:
        if self.mqtt_client is None or not self.mqtt_client.connected:
            return False
        receipt = self.mqtt_client.publish(topic, payload, qos=1, retain=True)
        return_code = getattr(receipt, "rc", 0)
        return return_code in (0, None)

    def system_state(self, session: Session) -> dict[str, object]:
        self.refresh_health()
        payload = build_system_state(
            session,
            property_key=self.registry.property.key,
            now=datetime.now(UTC),
            mqtt_connected=self.mqtt_client.connected if self.mqtt_client is not None else False,
            mqtt_required=self.settings.mqtt_enabled,
        )
        payload.update(
            {
                "runtime_ready": self.health.ready,
                "clock_polling_enabled": self.settings.clock_polling_enabled,
                "policy_scheduler_enabled": self.settings.policy_scheduler_enabled,
                "outbox_worker_enabled": self.settings.outbox_worker_enabled,
                "worker_errors": dict(self.health.worker_errors),
            }
        )
        return payload

    def _verify_database(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text("select 1"))
        self.health.database_connected = True

    def _verify_migration_head(self) -> None:
        config = Config(str(Path("alembic.ini")))
        script = ScriptDirectory.from_config(config)
        expected_head = script.get_current_head()
        with self.engine.connect() as connection:
            current = MigrationContext.configure(connection).get_current_revision()
        if current != expected_head:
            self.health.errors.append(
                f"database migration is not current: current={current}, expected={expected_head}"
            )
            return
        self.health.migration_current = True

    def _build_clock_client(self) -> tuple[ClockClient | None, ClockFieldMapping | None]:
        if self.settings.clock_client_mode == "disabled":
            return None, None
        mapping = load_yaml_model(self.settings.clock_field_mapping_path, ClockFieldMapping)
        if self.settings.clock_client_mode == "fixture":
            assert self.settings.clock_fixture_bookings_path is not None
            return (
                FixtureClockClient(
                    self.settings.clock_fixture_bookings_path,
                    self.settings.clock_fixture_rooms_path,
                ),
                mapping,
            )
        return ClockRestClient(self.settings), mapping

    def _start_background_tasks(self) -> None:
        if self.settings.clock_polling_enabled and self.clock_client is not None:
            self._tasks.append(
                asyncio.create_task(
                    self._periodic(
                        "clock-sync",
                        self.settings.clock_poll_interval_seconds,
                        self.run_sync_once,
                    )
                )
            )
        if self.settings.policy_scheduler_enabled:
            self._tasks.append(
                asyncio.create_task(
                    self._periodic(
                        "policy",
                        self.settings.policy_tick_seconds,
                        self.run_policy_once,
                    )
                )
            )
        if self.settings.outbox_worker_enabled and self.mqtt_client is not None:
            self._tasks.append(
                asyncio.create_task(
                    self._periodic(
                        "outbox",
                        self.settings.outbox_poll_seconds,
                        self.run_outbox_once,
                    )
                )
            )

    async def _periodic(
        self,
        name: str,
        interval_seconds: int,
        callback: Callable[[], Awaitable[object]],
    ) -> None:
        while not self._stopping.is_set():
            try:
                await callback()
                self.health.worker_errors.pop(name, None)
            except Exception as exc:
                self.health.worker_errors[name] = exc.__class__.__name__
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=interval_seconds)
            except TimeoutError:
                continue


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    runtime = AppRuntime(Settings())
    app.state.runtime = runtime
    await runtime.start()
    try:
        yield
    finally:
        await runtime.stop()
