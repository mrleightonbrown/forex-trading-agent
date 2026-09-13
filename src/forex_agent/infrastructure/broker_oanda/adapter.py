"""OANDA v20 REST API adapter implementing `BrokerPort`.

FX-4. Practice environment only, per CLAUDE.md safety rules — see
`_require_practice_host`. Provider-specific objects (raw JSON, httpx types)
never escape this module: every method returns a `domain` value object or
raises one of `forex_agent.application.ports.exceptions`.
"""

from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

import httpx

from forex_agent.application.ports.exceptions import (
    BrokerPortError,
    BrokerUnavailableError,
    InstrumentNotAvailableError,
)
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.money import Money
from forex_agent.domain.price import Price

PRACTICE_HOST = "api-fxpractice.oanda.com"
DEFAULT_BASE_URL = f"https://{PRACTICE_HOST}"
_TIMEOUT_SECONDS = 10.0


class NonPracticeHostError(BrokerPortError):
    """Raised when configured with anything other than OANDA's practice
    host. Independent of `Settings`' own PAPER/PRACTICE validation, since
    `OANDA_API_BASE_URL` is a separately-configurable value."""


def _require_practice_host(base_url: str) -> None:
    host = urlsplit(base_url).hostname
    if host != PRACTICE_HOST:
        raise NonPracticeHostError(
            f"OandaBrokerAdapter refuses to operate against host {host!r}; "
            f"only {PRACTICE_HOST!r} (practice) is permitted in V1"
        )


class OandaBrokerAdapter:
    """Implements `BrokerPort` against OANDA's v20 REST practice API."""

    def __init__(
        self,
        api_key: str,
        account_id: str,
        base_url: str = DEFAULT_BASE_URL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        _require_practice_host(base_url)
        self._account_id = account_id
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=_TIMEOUT_SECONDS,
        )

    async def aclose(self) -> None:
        """Close the underlying HTTP client, if this adapter created it."""
        if self._owns_client:
            await self._client.aclose()

    async def get_price(self, instrument: Instrument) -> Price:
        symbol = instrument.symbol
        try:
            response = await self._client.get(
                f"/v3/accounts/{self._account_id}/pricing",
                params={"instruments": symbol},
                headers=self._headers,
            )
        except httpx.RequestError as exc:
            raise BrokerUnavailableError(f"failed to reach OANDA: {exc}") from exc

        if response.status_code == 400:
            # OANDA returns 400 for an unrecognized/untradeable instrument —
            # every other request parameter is under our control.
            raise InstrumentNotAvailableError(instrument)
        if response.status_code >= 400:
            raise BrokerUnavailableError(
                f"OANDA pricing request failed with status {response.status_code}: {response.text}"
            )

        payload = _parse_json(response)
        prices = payload.get("prices")
        if prices is None:
            raise BrokerUnavailableError("unexpected OANDA response shape: missing 'prices' key")

        entry = next((p for p in prices if p.get("instrument") == symbol), None)
        if entry is None:
            raise InstrumentNotAvailableError(instrument)

        bids = entry.get("bids") or []
        asks = entry.get("asks") or []
        if not bids or not asks:
            raise InstrumentNotAvailableError(instrument)

        try:
            bid = Decimal(bids[0]["price"])
            ask = Decimal(asks[0]["price"])
        except (KeyError, InvalidOperation) as exc:
            raise BrokerUnavailableError(f"unexpected OANDA price entry shape: {exc}") from exc

        return Price(bid=bid, ask=ask)

    async def get_account_balance(self) -> Money:
        try:
            response = await self._client.get(
                f"/v3/accounts/{self._account_id}/summary", headers=self._headers
            )
        except httpx.RequestError as exc:
            raise BrokerUnavailableError(f"failed to reach OANDA: {exc}") from exc

        if response.status_code >= 400:
            raise BrokerUnavailableError(
                f"OANDA account summary request failed with status {response.status_code}: "
                f"{response.text}"
            )

        payload = _parse_json(response)
        account = payload.get("account")
        if account is None:
            raise BrokerUnavailableError("unexpected OANDA response shape: missing 'account' key")

        try:
            balance = Decimal(account["balance"])
            currency = account["currency"]
        except (KeyError, InvalidOperation) as exc:
            raise BrokerUnavailableError(f"unexpected OANDA account shape: {exc}") from exc

        return Money(balance, currency)


def _parse_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = response.json()
    except ValueError as exc:
        raise BrokerUnavailableError(f"OANDA returned a non-JSON response: {exc}") from exc
    return payload
