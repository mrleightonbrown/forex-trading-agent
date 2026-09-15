"""FX-14: EmaCrossoverStrategy run through run_backtest + simulate_trades
against real OANDA practice candles — proves the whole pipeline works
with a real strategy, not just synthetic fixtures. Auto-skipped when
OANDA credentials aren't configured — same pattern as FX-4's live tests.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest

from forex_agent.apps.settings import get_settings
from forex_agent.domain.backtest import run_backtest
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.simulated_trade import SimulatedTrade
from forex_agent.domain.strategies.ema_crossover import EmaCrossoverStrategy
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
async def test_ema_crossover_against_live_practice_candles(
    adapter: OandaMarketDataAdapter,
) -> None:
    eur_usd = Instrument(base_currency="EUR", quote_currency="USD")
    end = UtcTimestamp(datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(minutes=5))
    start = UtcTimestamp(end.value - timedelta(hours=4))

    candles = await adapter.get_candles(eur_usd, Granularity.M1, start, end)
    finalized = [c for c in candles if c.is_finalized]
    assert len(finalized) > 60, "expected enough live candles for a meaningful run"

    strategy = EmaCrossoverStrategy(fast_period=20, slow_period=50)
    hypotheses = run_backtest(strategy, finalized)
    trades = simulate_trades(hypotheses, finalized)

    # Not asserting *how many* signals fired — that depends on live
    # market behavior — only that whatever came out is internally
    # consistent with what the strategy and simulator guarantee.
    for hypothesis in hypotheses:
        assert hypothesis.strategy_key == "ema_crossover_v1"
        assert hypothesis.instrument == eur_usd

    _assert_trades_are_well_formed(trades)


def _assert_trades_are_well_formed(trades: list[SimulatedTrade]) -> None:
    for trade in trades:
        assert trade.entry_price > 0
        assert trade.exit_price > 0
        assert trade.exit_time.value >= trade.entry_time.value
