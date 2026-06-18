from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TypeVar

from app.domain.enums import ManualHvacMode
from app.domain.models import DesiredRoomIntent
from app.g301_adapter.planner import (
    G301Plan,
    G301PlanningError,
    RegisterWrite,
    compare_readback,
    plan_room_intent,
)
from app.g301_adapter.registers import G301DeviceProfile, G301Register, build_device_profile
from app.g301_adapter.transport import (
    G301DeviceOffline,
    G301ModbusException,
    G301ProtocolError,
    G301RegisterClient,
    G301TransportError,
    G301TransportTimeout,
)
from app.mqtt.schemas import IntentExecutionResult, RegisterWriteResult

T = TypeVar("T")


class IntentAttemptPhase(StrEnum):
    RETRYABLE = "retryable"
    WRITING = "writing"
    VERIFICATION_PENDING = "verification_pending"
    TERMINAL = "terminal"


@dataclass(frozen=True)
class IntentVersionState:
    last_seen_version: int | None = None
    last_terminal_version: int | None = None
    last_applied_version: int | None = None
    current_phase: IntentAttemptPhase | None = None


@dataclass
class _IntentAttempt:
    version: int
    payload_fingerprint: str
    phase: IntentAttemptPhase = IntentAttemptPhase.RETRYABLE
    plan: G301Plan | None = None
    completed_writes: list[RegisterWriteResult] = field(default_factory=list)
    cached_result: IntentExecutionResult | None = None


@dataclass
class _RoomIntentState:
    last_seen_version: int | None = None
    last_terminal_version: int | None = None
    last_applied_version: int | None = None
    current_attempt: _IntentAttempt | None = None


class G301EntranceWorker:
    def __init__(
        self,
        *,
        entrance_key: str,
        room_slave_addresses: Mapping[str, int],
        client: G301RegisterClient,
        operation_timeout_seconds: float = 5.0,
        max_operation_attempts: int = 3,
        retry_backoff_seconds: float = 0.1,
        readback_attempts: int = 3,
        readback_delay_seconds: float = 1.0,
    ) -> None:
        if operation_timeout_seconds <= 0:
            raise ValueError("operation_timeout_seconds must be positive")
        if max_operation_attempts < 1:
            raise ValueError("max_operation_attempts must be at least 1")
        if readback_attempts < 1:
            raise ValueError("readback_attempts must be at least 1")
        if retry_backoff_seconds < 0 or readback_delay_seconds < 0:
            raise ValueError("retry and readback delays cannot be negative")
        self.entrance_key = entrance_key
        self.room_slave_addresses = dict(room_slave_addresses)
        self.client = client
        self.operation_timeout_seconds = operation_timeout_seconds
        self.max_operation_attempts = max_operation_attempts
        self.retry_backoff_seconds = retry_backoff_seconds
        self.readback_attempts = readback_attempts
        self.readback_delay_seconds = readback_delay_seconds
        self._bus_lock = asyncio.Lock()
        self._intent_states: dict[str, _RoomIntentState] = {}

    def intent_version_state(self, room_key: str) -> IntentVersionState:
        state = self._intent_states.get(room_key)
        if state is None:
            return IntentVersionState()
        return IntentVersionState(
            last_seen_version=state.last_seen_version,
            last_terminal_version=state.last_terminal_version,
            last_applied_version=state.last_applied_version,
            current_phase=(
                state.current_attempt.phase if state.current_attempt is not None else None
            ),
        )

    async def apply_intent(self, intent: DesiredRoomIntent) -> IntentExecutionResult:
        async with self._bus_lock:
            return await self._apply_intent_serialized(intent)

    async def _apply_intent_serialized(
        self,
        intent: DesiredRoomIntent,
    ) -> IntentExecutionResult:
        slave_address = self.room_slave_addresses.get(intent.room_key)
        if slave_address is None:
            return self._result(
                intent,
                status="skipped",
                message="room has no configured G301 slave address for this entrance",
            )

        state = self._intent_states.setdefault(intent.room_key, _RoomIntentState())
        fingerprint = _intent_fingerprint(intent)
        if state.last_seen_version is not None and intent.intent_version < state.last_seen_version:
            return self._result(
                intent,
                status="stale",
                message=f"intent version is older than seen version {state.last_seen_version}",
            )

        if state.last_seen_version is None or intent.intent_version > state.last_seen_version:
            state.last_seen_version = intent.intent_version
            state.current_attempt = _IntentAttempt(
                version=intent.intent_version,
                payload_fingerprint=fingerprint,
            )
        else:
            attempt = state.current_attempt
            if attempt is None or attempt.version != intent.intent_version:
                raise RuntimeError("G301 intent version state is inconsistent")
            if attempt.payload_fingerprint != fingerprint:
                return self._result(
                    intent,
                    status="rejected",
                    message="same intent version was received with a different payload",
                )
            if attempt.phase == IntentAttemptPhase.TERMINAL:
                assert attempt.cached_result is not None
                return attempt.cached_result.model_copy(
                    update={"correlation_id": intent.correlation_id}
                )
            if attempt.phase in {
                IntentAttemptPhase.WRITING,
                IntentAttemptPhase.VERIFICATION_PENDING,
            }:
                return await self._resume_verification(
                    intent,
                    slave_address=slave_address,
                    state=state,
                    attempt=attempt,
                )

        assert state.current_attempt is not None
        return await self._execute_intent(
            intent,
            slave_address=slave_address,
            state=state,
            attempt=state.current_attempt,
        )

    async def _execute_intent(
        self,
        intent: DesiredRoomIntent,
        *,
        slave_address: int,
        state: _RoomIntentState,
        attempt: _IntentAttempt,
    ) -> IntentExecutionResult:
        attempt.phase = IntentAttemptPhase.RETRYABLE
        attempt.plan = None
        attempt.completed_writes.clear()
        try:
            profile = None
            if intent.hvac.enabled and intent.hvac.mode != ManualHvacMode.OFF:
                profile = await self._read_device_profile(slave_address)
            plan = plan_room_intent(
                intent,
                slave_address=slave_address,
                device_profile=profile,
            )
        except G301PlanningError as exc:
            result = self._result(intent, status="rejected", message=str(exc))
            return self._mark_terminal(state, attempt, result)
        except ValueError as exc:
            result = self._transport_failure_result(intent, exc)
            return self._mark_terminal(state, attempt, result)
        except G301TransportError as exc:
            result = self._transport_failure_result(intent, exc)
            if not exc.retryable:
                return self._mark_terminal(state, attempt, result)
            return result

        attempt.plan = plan
        attempt.phase = IntentAttemptPhase.WRITING
        try:
            for write in plan.writes:
                await self._write_one(slave_address, write)
                attempt.completed_writes.append(
                    RegisterWriteResult(address=f"0x{write.address:04X}", value=write.value)
                )
        except G301TransportError as exc:
            result = self._transport_failure_result(
                intent,
                exc,
                register_writes=attempt.completed_writes,
            )
            if not exc.retryable:
                return self._mark_terminal(state, attempt, result)
            attempt.phase = IntentAttemptPhase.VERIFICATION_PENDING
            return result

        attempt.phase = IntentAttemptPhase.VERIFICATION_PENDING
        verification_result = await self._verify_attempt(intent, state=state, attempt=attempt)
        assert verification_result is not None
        return verification_result

    async def _resume_verification(
        self,
        intent: DesiredRoomIntent,
        *,
        slave_address: int,
        state: _RoomIntentState,
        attempt: _IntentAttempt,
    ) -> IntentExecutionResult:
        if attempt.plan is None:
            attempt.phase = IntentAttemptPhase.RETRYABLE
            return await self._execute_intent(
                intent,
                slave_address=slave_address,
                state=state,
                attempt=attempt,
            )
        result = await self._verify_attempt(
            intent,
            state=state,
            attempt=attempt,
            terminal_on_mismatch=False,
        )
        if result is not None:
            return result

        attempt.phase = IntentAttemptPhase.RETRYABLE
        return await self._execute_intent(
            intent,
            slave_address=slave_address,
            state=state,
            attempt=attempt,
        )

    async def _verify_attempt(
        self,
        intent: DesiredRoomIntent,
        *,
        state: _RoomIntentState,
        attempt: _IntentAttempt,
        terminal_on_mismatch: bool = True,
    ) -> IntentExecutionResult | None:
        assert attempt.plan is not None
        try:
            observed = await self._readback(attempt.plan)
        except G301TransportError as exc:
            result = self._result(
                intent,
                status="applied_unconfirmed",
                message=f"write outcome is uncertain and status verification failed: {exc}",
                register_writes=attempt.completed_writes,
            )
            if not exc.retryable:
                return self._mark_terminal(state, attempt, result)
            return result

        mismatches = compare_readback(attempt.plan, observed)
        if mismatches and not terminal_on_mismatch:
            return None
        result = self._result(
            intent,
            status="readback_mismatch" if mismatches else "applied",
            message=None if not mismatches else "G301 actual state did not match the desired state",
            register_writes=attempt.completed_writes,
            mismatches={
                f"0x{mismatch.address:04X}": {
                    "expected": mismatch.expected,
                    "observed": mismatch.observed,
                    "description": mismatch.description,
                }
                for mismatch in mismatches
            },
        )
        return self._mark_terminal(state, attempt, result, applied=not mismatches)

    @staticmethod
    def _mark_terminal(
        state: _RoomIntentState,
        attempt: _IntentAttempt,
        result: IntentExecutionResult,
        *,
        applied: bool = False,
    ) -> IntentExecutionResult:
        attempt.phase = IntentAttemptPhase.TERMINAL
        attempt.cached_result = result
        state.last_terminal_version = attempt.version
        if applied:
            state.last_applied_version = attempt.version
        return result

    async def _write_one(self, slave_address: int, write: RegisterWrite) -> None:
        await self._with_retry(
            lambda: self.client.write_register(
                slave_address=slave_address,
                address=write.address,
                value=write.value,
            )
        )

    async def _read_device_profile(self, slave_address: int) -> G301DeviceProfile:
        capabilities_raw = await self._read_one(slave_address, G301Register.CAPABILITIES)
        limits = await self._with_retry(
            lambda: self.client.read_holding_registers(
                slave_address=slave_address,
                address=G301Register.MODE_LIMITATION,
                count=3,
            )
        )
        if len(limits) != 3:
            raise G301ProtocolError("G301 limit read returned an incomplete response")
        try:
            return build_device_profile(
                capabilities_raw=capabilities_raw,
                mode_limitation_raw=limits[0],
                upper_temperature_raw=limits[1],
                lower_temperature_raw=limits[2],
            )
        except ValueError as exc:
            raise G301PlanningError(str(exc)) from exc

    async def _readback(self, plan: G301Plan) -> dict[int, int]:
        observed: dict[int, int] = {}
        for attempt in range(self.readback_attempts):
            observed = {
                expectation.address: await self._read_one(
                    plan.slave_address,
                    expectation.address,
                )
                for expectation in plan.readback_expectations
            }
            if not compare_readback(plan, observed):
                return observed
            if attempt + 1 < self.readback_attempts and self.readback_delay_seconds:
                await asyncio.sleep(self.readback_delay_seconds)
        return observed

    async def _read_one(self, slave_address: int, address: int) -> int:
        values = await self._with_retry(
            lambda: self.client.read_holding_registers(
                slave_address=slave_address,
                address=address,
                count=1,
            )
        )
        if len(values) != 1:
            raise G301ProtocolError("G301 register read returned an incomplete response")
        return values[0]

    async def _with_retry(self, operation: Callable[[], Awaitable[T]]) -> T:
        last_error: G301TransportError | None = None
        for attempt in range(self.max_operation_attempts):
            try:
                return await asyncio.wait_for(
                    operation(),
                    timeout=self.operation_timeout_seconds,
                )
            except TimeoutError as exc:
                last_error = G301TransportTimeout("G301 operation timed out")
                last_error.__cause__ = exc
            except G301TransportError as exc:
                last_error = exc
                if not exc.retryable:
                    raise
            if attempt + 1 < self.max_operation_attempts and self.retry_backoff_seconds:
                await asyncio.sleep(self.retry_backoff_seconds * (2**attempt))
        assert last_error is not None
        raise last_error

    def _transport_failure_result(
        self,
        intent: DesiredRoomIntent,
        exc: Exception,
        *,
        register_writes: list[RegisterWriteResult] | None = None,
    ) -> IntentExecutionResult:
        if isinstance(exc, G301DeviceOffline):
            status = "device_offline"
        elif isinstance(exc, G301TransportTimeout):
            status = "timeout"
        elif isinstance(exc, G301ModbusException):
            status = "modbus_exception"
        elif isinstance(exc, G301PlanningError | ValueError):
            status = "rejected"
        else:
            status = "failed"
        return self._result(
            intent,
            status=status,
            message=str(exc),
            register_writes=register_writes,
        )

    @staticmethod
    def _result(
        intent: DesiredRoomIntent,
        *,
        status: str,
        message: str | None,
        register_writes: list[RegisterWriteResult] | None = None,
        mismatches: dict[str, dict[str, int | str | None]] | None = None,
    ) -> IntentExecutionResult:
        return IntentExecutionResult(
            room_key=intent.room_key,
            intent_version=intent.intent_version,
            status=status,
            message=message,
            applied_at=datetime.now(UTC),
            register_writes=register_writes or [],
            mismatches=mismatches or {},
            correlation_id=intent.correlation_id,
        )


def _intent_fingerprint(intent: DesiredRoomIntent) -> str:
    payload = json.dumps(
        intent.stable_payload(),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()
