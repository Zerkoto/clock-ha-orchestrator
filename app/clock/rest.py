from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from app.clock.interface import ClockApiContract, ClockClient, ClockMappingRequired, ClockPage
from app.settings import Settings


class ClockRestClient(ClockClient):
    """REST client that refuses to guess Clock endpoint paths or payload shapes."""

    def __init__(self, settings: Settings, contract: ClockApiContract | None = None) -> None:
        self._settings = settings
        self._contract = contract
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
        contract = self._require_confirmed_contract()
        params: dict[str, str] = {}
        if updated_since is not None:
            if contract.bookings.updated_since_filter is None:
                raise ClockMappingRequired(
                    "Clock bookings incremental filter is not verified in the live contract"
                )
            params[contract.bookings.updated_since_filter] = updated_since.isoformat()
        if cursor is not None:
            if not contract.bookings.supports_pagination:
                raise ClockMappingRequired(
                    "Clock bookings pagination is not verified in the live contract"
                )
            assert contract.bookings.cursor_query_param is not None
            params[contract.bookings.cursor_query_param] = cursor
        payload = await self._get_json(contract.bookings.endpoint_path, params=params)
        if contract.bookings.response_items_key is None and isinstance(payload, list):
            return ClockPage(items=payload)
        items_key = contract.bookings.response_items_key
        if items_key and isinstance(payload, dict) and isinstance(payload.get(items_key), list):
            next_cursor = (
                payload.get(contract.bookings.next_cursor_key)
                if contract.bookings.next_cursor_key
                else None
            )
            return ClockPage(
                items=payload[items_key],
                next_cursor=str(next_cursor) if next_cursor is not None else None,
            )
        raise ClockMappingRequired("Clock bookings response shape does not match verified contract")

    async def list_rooms(self) -> list[dict[str, Any]]:
        contract = self._require_confirmed_contract()
        payload = await self._get_json(contract.rooms.endpoint_path, params={})
        if contract.rooms.response_items_key is None and isinstance(payload, list):
            return payload
        items_key = contract.rooms.response_items_key
        if items_key and isinstance(payload, dict) and isinstance(payload.get(items_key), list):
            return payload[items_key]
        raise ClockMappingRequired("Clock rooms response shape does not match verified contract")

    def _require_confirmed_contract(self) -> ClockApiContract:
        if self._contract is None:
            raise ClockMappingRequired(
                "Live Clock adapter is disabled until a verified ClockApiContract is supplied "
                "from official Clock documentation or sanitized sandbox evidence."
            )
        self._contract.require_live_ready()
        return self._contract

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
