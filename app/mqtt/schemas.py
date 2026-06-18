from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import ManualHvacMode


class ReportedHvacState(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool
    mode: ManualHvacMode
    target_temperature_c: float | None = None


class ReportedRoomState(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    room_key: str
    intent_version: int | None = None
    online: bool
    reported_at: datetime
    hvac: ReportedHvacState
    ambient_temperature_c: float | None = None
    faults: list[str] = Field(default_factory=list)
    device_model: str | None = None
    firmware_version: str | None = None
    capability_profile: dict[str, bool | int | str] | None = None
    last_successful_command_version: int | None = None
    local_change_detected: bool = False
    raw_registers: dict[str, int] | None = None
    correlation_id: UUID | None = None


class RegisterWriteResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    address: str
    value: int


class IntentExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    room_key: str
    intent_version: int
    status: Literal[
        "accepted",
        "queued",
        "writing",
        "applied",
        "applied_unconfirmed",
        "rejected",
        "timeout",
        "modbus_exception",
        "readback_mismatch",
        "device_offline",
        "stale",
        "failed",
        "skipped",
    ]
    message: str | None = None
    applied_at: datetime
    register_writes: list[RegisterWriteResult] = Field(default_factory=list)
    mismatches: dict[str, dict[str, int | str | None]] = Field(default_factory=dict)
    correlation_id: UUID


class EntranceAdapterState(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    entrance_key: str
    status: Literal["idle", "polling", "commanding", "degraded", "offline"]
    adapter_online: bool
    gateway_online: bool
    room_mismatches: int = Field(default=0, ge=0)
    last_poll_at: datetime | None = None
    last_successful_poll_at: datetime | None = None
    gateway_latency_ms: float | None = Field(default=None, ge=0)
    consecutive_failures: int = Field(default=0, ge=0)
    last_modbus_exception: str | None = None
    configured_slaves: int = Field(default=0, ge=0)
    online_slaves: int = Field(default=0, ge=0)
    offline_slaves: int = Field(default=0, ge=0)
    scan_duration_ms: float | None = Field(default=None, ge=0)
    command_queue_depth: int = Field(default=0, ge=0)
    updated_at: datetime
