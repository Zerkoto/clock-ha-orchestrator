from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Protocol

from app.domain.models import DesiredRoomIntent
from app.g301_adapter.planner import (
    G301PlanningError,
    compare_readback,
    plan_room_intent,
)
from app.mqtt.schemas import IntentExecutionResult, RegisterWriteResult


class G301RegisterClient(Protocol):
    def write_register(self, address: int, value: int) -> None:
        pass

    def read_holding_registers(self, address: int, count: int) -> list[int]:
        pass


class G301EntranceWorker:
    def __init__(
        self,
        *,
        entrance_key: str,
        room_slave_addresses: Mapping[str, int],
        client: G301RegisterClient,
    ) -> None:
        self.entrance_key = entrance_key
        self.room_slave_addresses = dict(room_slave_addresses)
        self.client = client

    def apply_intent(self, intent: DesiredRoomIntent) -> IntentExecutionResult:
        now = datetime.now(UTC)
        slave_address = self.room_slave_addresses.get(intent.room_key)
        if slave_address is None:
            return IntentExecutionResult(
                room_key=intent.room_key,
                intent_version=intent.intent_version,
                status="skipped",
                message="room has no configured G301 slave address for this entrance",
                applied_at=now,
                correlation_id=intent.correlation_id,
            )

        try:
            plan = plan_room_intent(intent, slave_address=slave_address)
        except G301PlanningError as exc:
            return IntentExecutionResult(
                room_key=intent.room_key,
                intent_version=intent.intent_version,
                status="failed",
                message=str(exc),
                applied_at=now,
                correlation_id=intent.correlation_id,
            )

        for write in plan.writes:
            self.client.write_register(write.address, write.value)
        observed = {
            address: self.client.read_holding_registers(address, 1)[0]
            for address in plan.expected_readback
        }
        mismatches = compare_readback(plan, observed)
        status = "readback_mismatch" if mismatches else "applied"
        return IntentExecutionResult(
            room_key=intent.room_key,
            intent_version=intent.intent_version,
            status=status,
            message=None if not mismatches else "G301 readback did not match planned writes",
            applied_at=now,
            register_writes=[
                RegisterWriteResult(address=f"0x{write.address:04X}", value=write.value)
                for write in plan.writes
            ],
            mismatches={
                f"0x{mismatch.address:04X}": {
                    "expected": mismatch.expected,
                    "observed": mismatch.observed,
                }
                for mismatch in mismatches
            },
            correlation_id=intent.correlation_id,
        )
