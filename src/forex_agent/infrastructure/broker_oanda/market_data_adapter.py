"""OANDA v20 REST API adapter implementing `MarketDataPort` (FX-6).

Confirmed live against the practice API before writing this:
- `/v3/instruments/{instrument}/candles` takes no account ID.
- Its `time` field (e.g. "2026-09-11T20:57:00.000000000Z", nanosecond
  precision) parses directly with Python 3.12's `datetime.fromisoformat` —
  no manual string handling needed.
- OANDA caps `count` at 5000 and returns HTTP 400 ("Maximum value for
  'count' exceeded") for a `from`/`to` range implying more than that,
  rather than silently truncating the response.
- (FX-24) `dailyAlignment=17`/`alignmentTimezone=America/New_York`
  produce byte-identical results to omitting them — the practice API's
  default already matches. Sent explicitly anyway, confirmed live, so
  this adapter's own correctness doesn't silently depend on OANDA's
  default never changing; `domain.candle_aggregation`'s NY-anchored
  day-aligned bucketing (FX-24) assumes exactly this alignment.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from forex_agent.application.ports.exceptions import (
    BrokerUnavailableError,
    CandleRangeTooLargeError,
    InstrumentNotAvailableError,
)
from forex_agent.domain.candle import Candle
from forex_agent.domain.candle_source import CandleSource
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.broker_oanda._shared import (
    DEFAULT_BASE_URL,
    error_message,
    parse_json,
    require_practice_host,
)

_TIMEOUT_SECONDS = 10.0


class OandaMarketDataAdapter:
    """Implements `MarketDataPort` against OANDA's v20 REST practice API."""

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        require_practice_host(base_url)
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

    async def get_candles(
        self,
        instrument: Instrument,
        granularity: Granularity,
        start: UtcTimestamp,
        end: UtcTimestamp,
    ) -> list[Candle]:
        symbol = instrument.symbol
        try:
            response = await self._client.get(
                f"/v3/instruments/{symbol}/candles",
                params={
                    "granularity": granularity.value,
                    "from": start.value.isoformat(),
                    "to": end.value.isoformat(),
                    "price": "BA",
                    "dailyAlignment": 17,
                    "alignmentTimezone": "America/New_York",
                },
                headers=self._headers,
            )
        except httpx.RequestError as exc:
            raise BrokerUnavailableError(f"failed to reach OANDA: {exc}") from exc

        if response.status_code == 400:
            if "count" in error_message(response).lower():
                raise CandleRangeTooLargeError(instrument, granularity, start, end)
            raise InstrumentNotAvailableError(instrument)
        if response.status_code >= 400:
            raise BrokerUnavailableError(
                f"OANDA candles request failed with status {response.status_code}: {response.text}"
            )

        payload = parse_json(response)
        raw_candles = payload.get("candles")
        if raw_candles is None:
            raise BrokerUnavailableError("unexpected OANDA response shape: missing 'candles' key")

        try:
            return [_to_candle(instrument, granularity, raw) for raw in raw_candles]
        except (KeyError, InvalidOperation, ValueError) as exc:
            raise BrokerUnavailableError(f"unexpected OANDA candle shape: {exc}") from exc


def _to_candle(instrument: Instrument, granularity: Granularity, raw: dict[str, Any]) -> Candle:
    return Candle(
        instrument=instrument,
        granularity=granularity,
        start_time=UtcTimestamp(datetime.fromisoformat(raw["time"])),
        bid=_to_ohlc(raw["bid"]),
        ask=_to_ohlc(raw["ask"]),
        volume=int(raw["volume"]),
        is_finalized=bool(raw["complete"]),
        source=CandleSource.NATIVE,  # explicit, even though it's the default (FX-24)
    )


def _to_ohlc(raw: dict[str, Any]) -> Ohlc:
    return Ohlc(
        open=Decimal(raw["o"]),
        high=Decimal(raw["h"]),
        low=Decimal(raw["l"]),
        close=Decimal(raw["c"]),
    )
