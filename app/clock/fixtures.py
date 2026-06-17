from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.clock.interface import ClockClient, ClockPage


class FixtureClockClient(ClockClient):
    def __init__(self, bookings_path: Path, rooms_path: Path | None = None) -> None:
        self._bookings_path = bookings_path
        self._rooms_path = rooms_path

    async def list_bookings(
        self,
        *,
        updated_since: datetime | None,
        cursor: str | None = None,
    ) -> ClockPage:
        del updated_since, cursor
        return ClockPage(items=_load_json_list(self._bookings_path))

    async def list_rooms(self) -> list[dict[str, Any]]:
        if self._rooms_path is None:
            return []
        return _load_json_list(self._rooms_path)


def _load_json_list(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, list):
        raise ValueError(f"fixture must contain a JSON list: {path}")
    return payload
