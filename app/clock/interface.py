from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


class ClockMappingRequired(RuntimeError):
    """Raised when live Clock behavior has not been documented or sandbox-confirmed."""


@dataclass(frozen=True)
class ClockPage:
    items: list[dict[str, Any]]
    next_cursor: str | None = None


class ClockClient(Protocol):
    async def list_bookings(
        self,
        *,
        updated_since: datetime | None,
        cursor: str | None = None,
    ) -> ClockPage:
        """Return raw Clock booking payloads from a documented, sandbox-confirmed endpoint."""

    async def list_rooms(self) -> list[dict[str, Any]]:
        """Return raw Clock physical room payloads from a documented, sandbox-confirmed endpoint."""

