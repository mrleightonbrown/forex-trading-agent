"""Live end-to-end check against the real OANDA practice API.

Auto-skipped when OANDA credentials aren't configured — same pattern as
FX-4's test_oanda_broker_adapter.py.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest

from forex_agent.apps.settings import get_settings
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.broker_oanda.market_data_adapter import OandaMarketDataAdapter


def _oanda_credentials_available() -> bool:
    settings = get_settings()
    return bool(settings.oanda_api_key)


pytestmark = pytest.mark.skipif(
    not _oanda_credentials_available(),
    reason="OANDA_API_KEY not configured; skipping live OANDA check",
)


@pytest.fixture
async def adapter() -> AsyncIterator[OandaMarketDataAdapter]:
    settings = get_settings()
    assert settings.oanda_api_key is not None

    market_data = OandaMarketDataAdapter(
        api_key=settings.oanda_api_key,
        base_url=settings.oanda_api_base_url,
    )
    try:
        yield market_data
    finally:
        await market_data.aclose()


@pytest.mark.asyncio
async def test_get_candles_against_live_practice_api(adapter: OandaMarketDataAdapter) -> None:
    eur_usd = Instrument(base_currency="EUR", quote_currency="USD")
    # A fixed, market-open weekday window rather than "now" — "now" is
    # flaky over weekends/holidays, when forex markets are closed and this
    # would return zero candles.
    start = UtcTimestamp(datetime(2026, 9, 8, 12, 0, 0, tzinfo=UTC))
    end = UtcTimestamp(datetime(2026, 9, 8, 12, 5, 0, tzinfo=UTC))

    candles = await adapter.get_candles(eur_usd, Granularity.M1, start, end)

    assert len(candles) > 0
    for candle in candles:
        assert candle.bid.high >= candle.bid.low
        assert candle.ask.high >= candle.ask.low
