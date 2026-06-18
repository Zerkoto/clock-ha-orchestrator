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
    status: Literal["accepted", "applied", "readback_mismatch", "failed", "skipped"]
    message: str | None = None
    applied_at: datetime
    register_writes: list[RegisterWriteResult] = Field(default_factory=list)
    mismatches: dict[str, dict[str, int | None]] = Field(default_factory=dict)
    correlation_id: UUID


class EntranceAdapterState(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    entrance_key: str
    status: Literal["idle", "polling", "degraded", "offline"]
    adapter_online: bool
    gateway_online: bool
    room_mismatches: int = Field(default=0, ge=0)
    last_poll_at: datetime | None = None
    updated_at: datetime
