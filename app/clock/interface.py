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


@dataclass(frozen=True)
class ClockCollectionContract:
    """Verified list endpoint behavior for a Clock collection.

    This is deliberately explicit because Clock endpoint paths, filters,
    pagination and response envelopes must come from official documentation or
    sanitized sandbox evidence before live calls are enabled.
    """

    endpoint_path: str
    documentation_reference: str
    response_items_key: str | None = None
    next_cursor_key: str | None = None
    cursor_query_param: str | None = None
    updated_since_filter: str | None = None

    @property
    def supports_pagination(self) -> bool:
        return self.next_cursor_key is not None and self.cursor_query_param is not None

    @property
    def supports_incremental_filter(self) -> bool:
        return self.updated_since_filter is not None


@dataclass(frozen=True)
class ClockApiContract:
    bookings: ClockCollectionContract
    rooms: ClockCollectionContract
    physical_room_fields_confirmed: bool = False

    def require_live_ready(self) -> None:
        missing: list[str] = []
        if not self.bookings.documentation_reference:
            missing.append("bookings.documentation_reference")
        if not self.rooms.documentation_reference:
            missing.append("rooms.documentation_reference")
        if not self.physical_room_fields_confirmed:
            missing.append("physical_room_fields_confirmed")
        if missing:
            raise ClockMappingRequired(
                "Live Clock contract is incomplete; missing verified parts: " + ", ".join(missing)
            )


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
