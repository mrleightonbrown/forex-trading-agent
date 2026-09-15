"""FX-25: MultiTimeframeTrendStrategy run through run_backtest +
simulate_trades against real OANDA practice candles at two granularities
(H1 entry, H4 confirmation). Auto-skipped when OANDA credentials aren't
configured — same pattern as every other live test.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest

from forex_agent.apps.settings import get_settings
from forex_agent.domain.backtest import run_backtest
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.simulated_trade import SimulatedTrade
from forex_agent.domain.strategies.multi_timeframe_trend import MultiTimeframeTrendStrategy
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trade_simulation import simulate_trades
from forex_agent.infrastructure.broker_oanda.market_data_adapter import OandaMarketDataAdapter


def _oanda_credentials_available() -> bool:
    return bool(get_settings().oanda_api_key)


pytestmark = pytest.mark.skipif(
    not _oanda_credentials_available(),
    reason="OANDA_API_KEY not configured; skipping live OANDA check",
)


@pytest.fixture
async def adapter() -> AsyncIterator[OandaMarketDataAdapter]:
    settings = get_settings()
    assert settings.oanda_api_key is not None

    market_data = OandaMarketDataAdapter(
        api_key=settings.oanda_api_key, base_url=settings.oanda_api_base_url
    )
    try:
        yield market_data
    finally:
        await market_data.aclose()


@pytest.mark.asyncio
async def test_multi_timeframe_trend_against_live_practice_candles(
    adapter: OandaMarketDataAdapter,
) -> None:
    eur_usd = Instrument(base_currency="EUR", quote_currency="USD")
    end = UtcTimestamp(datetime.now(UTC).replace(minute=0, second=0, microsecond=0))
    # Enough H1 history for the default h1_slow_period=50, and enough H4
    # history (spanning the same window) for the default h4_slow_period=50
    # (needs 200+ H1-equivalent hours) -- 60 days comfortably covers both.
    start = UtcTimestamp(end.value - timedelta(days=60))

    h1_candles = await adapter.get_candles(eur_usd, Granularity.H1, start, end)
    h4_candles = await adapter.get_candles(eur_usd, Granularity.H4, start, end)
    h1_finalized = [c for c in h1_candles if c.is_finalized]
    h4_finalized = [c for c in h4_candles if c.is_finalized]
    assert len(h1_finalized) > 60, "expected enough live H1 candles for a meaningful run"
    assert len(h4_finalized) > 60, "expected enough live H4 candles for a meaningful run"

    strategy = MultiTimeframeTrendStrategy(h4_candles=h4_finalized)
    hypotheses = run_backtest(strategy, h1_finalized)
    trades = simulate_trades(hypotheses, h1_finalized)

    for hypothesis in hypotheses:
        assert hypothesis.strategy_key == "multi_timeframe_trend_v1"
        assert hypothesis.instrument == eur_usd
        assert hypothesis.timeframe is Granularity.H1

    _assert_trades_are_well_formed(trades)


def _assert_trades_are_well_formed(trades: list[SimulatedTrade]) -> None:
    for trade in trades:
        assert trade.entry_price > 0
        assert trade.exit_price > 0
        assert trade.exit_time.value >= trade.entry_time.value
