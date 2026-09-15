from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from forex_agent.application.ports.exceptions import (
    BrokerUnavailableError,
    CandleRangeTooLargeError,
    InstrumentNotAvailableError,
)
from forex_agent.domain.candle_source import CandleSource
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.broker_oanda._shared import NonPracticeHostError
from forex_agent.infrastructure.broker_oanda.market_data_adapter import OandaMarketDataAdapter

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")
START = UtcTimestamp(datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC))
END = UtcTimestamp(datetime(2026, 1, 1, 1, 0, 0, tzinfo=UTC))


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api-fxpractice.oanda.com",
    )


def _adapter(handler: Callable[[httpx.Request], httpx.Response]) -> OandaMarketDataAdapter:
    return OandaMarketDataAdapter(api_key="secret-token", client=_client(handler))


def test_rejects_non_practice_host() -> None:
    with pytest.raises(NonPracticeHostError):
        OandaMarketDataAdapter(api_key="x", base_url="https://api-fxtrade.oanda.com")


@pytest.mark.asyncio
async def test_get_candles_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v3/instruments/EUR_USD/candles"
        assert request.url.params["granularity"] == "M1"
        assert request.url.params["price"] == "BA"
        # FX-24: sent explicitly rather than relying on OANDA's default.
        assert request.url.params["dailyAlignment"] == "17"
        assert request.url.params["alignmentTimezone"] == "America/New_York"
        assert request.headers["Authorization"] == "Bearer secret-token"
        return httpx.Response(
            200,
            json={
                "instrument": "EUR_USD",
                "granularity": "M1",
                "candles": [
                    {
                        "complete": True,
                        "volume": 83,
                        "time": "2026-01-01T00:00:00.000000000Z",
                        "bid": {"o": "1.1000", "h": "1.1010", "l": "1.0990", "c": "1.1005"},
                        "ask": {"o": "1.1002", "h": "1.1012", "l": "1.0992", "c": "1.1007"},
                    },
                    {
                        "complete": False,
                        "volume": 5,
                        "time": "2026-01-01T00:01:00.000000000Z",
                        "bid": {"o": "1.1005", "h": "1.1006", "l": "1.1004", "c": "1.1004"},
                        "ask": {"o": "1.1007", "h": "1.1008", "l": "1.1006", "c": "1.1006"},
                    },
                ],
            },
        )

    candles = await _adapter(handler).get_candles(EUR_USD, Granularity.M1, START, END)

    assert len(candles) == 2
    first, second = candles
    assert first.instrument == EUR_USD
    assert first.granularity is Granularity.M1
    assert first.start_time == UtcTimestamp(datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC))
    assert first.bid == Ohlc(
        open=Decimal("1.1000"),
        high=Decimal("1.1010"),
        low=Decimal("1.0990"),
        close=Decimal("1.1005"),
    )
    assert first.volume == 83
    assert first.is_finalized is True
    assert first.source is CandleSource.NATIVE  # FX-24
    # a still-forming candle is stored too, marked not finalized
    assert second.is_finalized is False


@pytest.mark.asyncio
async def test_get_candles_invalid_instrument() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"errorMessage": "Invalid value specified for 'instrument'"}
        )

    with pytest.raises(InstrumentNotAvailableError):
        await _adapter(handler).get_candles(EUR_USD, Granularity.M1, START, END)


@pytest.mark.asyncio
async def test_get_candles_range_too_large() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"errorMessage": "Maximum value for 'count' exceeded"})

    with pytest.raises(CandleRangeTooLargeError):
        await _adapter(handler).get_candles(EUR_USD, Granularity.M1, START, END)


@pytest.mark.asyncio
async def test_get_candles_auth_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"errorMessage": "Insufficient authorization"})

    with pytest.raises(BrokerUnavailableError):
        await _adapter(handler).get_candles(EUR_USD, Granularity.M1, START, END)


@pytest.mark.asyncio
async def test_get_candles_network_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(BrokerUnavailableError):
        await _adapter(handler).get_candles(EUR_USD, Granularity.M1, START, END)


@pytest.mark.asyncio
async def test_get_candles_missing_candles_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    with pytest.raises(BrokerUnavailableError):
        await _adapter(handler).get_candles(EUR_USD, Granularity.M1, START, END)


@pytest.mark.asyncio
async def test_get_candles_malformed_candle_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"candles": [{"unexpected": "shape"}]})

    with pytest.raises(BrokerUnavailableError):
        await _adapter(handler).get_candles(EUR_USD, Granularity.M1, START, END)


@pytest.mark.asyncio
async def test_aclose_closes_self_created_client() -> None:
    adapter = OandaMarketDataAdapter(api_key="x")

    await adapter.aclose()

    assert adapter._client.is_closed
