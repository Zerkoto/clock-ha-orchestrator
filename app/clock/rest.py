from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from app.clock.interface import ClockClient, ClockMappingRequired, ClockPage
from app.settings import Settings


class ClockRestClient(ClockClient):
    """REST client that refuses to guess Clock endpoint paths or payload shapes."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._auth = None
        if settings.clock_api_key:
            self._auth = httpx.DigestAuth(
                settings.clock_api_user or "",
                settings.clock_api_key.get_secret_value(),
            )

    async def list_bookings(
        self,
        *,
        updated_since: datetime | None,
        cursor: str | None = None,
    ) -> ClockPage:
        self._require_confirmed_mapping()
        assert self._settings.clock_bookings_endpoint_path is not None
        params: dict[str, str] = {}
        if updated_since is not None:
            params["updated_at.gteq"] = updated_since.isoformat()
        if cursor is not None:
            params["cursor"] = cursor
        payload = await self._get_json(self._settings.clock_bookings_endpoint_path, params=params)
        if isinstance(payload, list):
            return ClockPage(items=payload)
        if isinstance(payload, dict) and isinstance(payload.get("items"), list):
            next_cursor = payload.get("next_cursor")
            return ClockPage(
                items=payload["items"],
                next_cursor=str(next_cursor) if next_cursor is not None else None,
            )
        raise ClockMappingRequired("Clock booking pagination shape must be confirmed in sandbox")

    async def list_rooms(self) -> list[dict[str, Any]]:
        self._require_confirmed_mapping()
        assert self._settings.clock_rooms_endpoint_path is not None
        payload = await self._get_json(self._settings.clock_rooms_endpoint_path, params={})
        if not isinstance(payload, list):
            raise ClockMappingRequired("Clock rooms response shape must be confirmed in sandbox")
        return payload

    def _require_confirmed_mapping(self) -> None:
        if not self._settings.live_clock_mapping_enabled:
            raise ClockMappingRequired(
                "Live Clock adapter requires CLOCK_BOOKINGS_ENDPOINT_PATH, "
                "CLOCK_ROOMS_ENDPOINT_PATH and CLOCK_ENDPOINT_DOC_REFERENCE to be filled from "
                "official Clock docs or sanitized sandbox evidence."
            )

    @retry(
        retry=retry_if_exception_type(
            (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError)
        ),
        wait=wait_exponential_jitter(initial=0.5, max=10),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    async def _get_json(self, path: str, *, params: dict[str, str]) -> Any:
        if self._auth is None:
            raise ClockMappingRequired("Clock Digest credentials are required for live API access")

        subscription_id = self._settings.clock_subscription_id
        account_id = self._settings.clock_account_id
        if not subscription_id or not account_id:
            raise ClockMappingRequired("Clock subscription and account IDs are required")

        path = path.format(subscription_id=subscription_id, account_id=account_id).lstrip("/")
        url = f"{self._settings.clock_base_url}/{path}"
        async with httpx.AsyncClient(auth=self._auth, timeout=30.0) as client:
            response = await client.get(
                url,
                params=params,
                headers={"Content-Type": "application/json"},
            )
            if response.status_code == 429:
                response.raise_for_status()
            if response.status_code >= 400:
                response.raise_for_status()
            return response.json()
