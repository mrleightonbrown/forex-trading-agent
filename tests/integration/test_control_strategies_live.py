"""FX-22: all four control strategies run through run_backtest +
simulate_trades against real OANDA practice candles. Auto-skipped when
OANDA credentials aren't configured — same pattern as every other live
test.

One consolidated file rather than four near-duplicates: none of these
four strategies have any numerical logic worth a dedicated live-data
check — this just confirms each runs cleanly against real data and
produces well-formed output (or, for NoTradeStrategy, none at all).
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest

from forex_agent.apps.settings import get_settings
from forex_agent.domain.backtest import run_backtest
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.simulated_trade import SimulatedTrade
from forex_agent.domain.strategies.control import (
    AlwaysLongStrategy,
    AlwaysShortStrategy,
    NoTradeStrategy,
    PreviousBarDirectionStrategy,
)
from forex_agent.domain.strategy import Strategy
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
async def test_control_strategies_against_live_practice_candles(
    adapter: OandaMarketDataAdapter,
) -> None:
    eur_usd = Instrument(base_currency="EUR", quote_currency="USD")
    end = UtcTimestamp(datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(minutes=5))
    start = UtcTimestamp(end.value - timedelta(hours=4))

    candles = await adapter.get_candles(eur_usd, Granularity.M1, start, end)
    finalized = [c for c in candles if c.is_finalized]
    assert len(finalized) > 30, "expected enough live candles for a meaningful run"

    strategies: list[tuple[str, Strategy]] = [
        ("always_long_v1", AlwaysLongStrategy()),
        ("always_short_v1", AlwaysShortStrategy()),
        ("previous_bar_direction_v1", PreviousBarDirectionStrategy()),
        ("no_trade_v1", NoTradeStrategy()),
    ]

    for strategy_key, strategy in strategies:
        hypotheses = run_backtest(strategy, finalized)
        trades = simulate_trades(hypotheses, finalized)

        for hypothesis in hypotheses:
            assert hypothesis.strategy_key == strategy_key
            assert hypothesis.instrument == eur_usd

        _assert_trades_are_well_formed(trades)

    # AlwaysLong/AlwaysShort must each produce exactly one held trade
    # over this window, same as the engineered-series test.
    always_long_trades = simulate_trades(run_backtest(AlwaysLongStrategy(), finalized), finalized)
    assert len(always_long_trades) == 1

    always_short_trades = simulate_trades(run_backtest(AlwaysShortStrategy(), finalized), finalized)
    assert len(always_short_trades) == 1

    # NoTradeStrategy must never produce anything.
    assert run_backtest(NoTradeStrategy(), finalized) == []


def _assert_trades_are_well_formed(trades: list[SimulatedTrade]) -> None:
    for trade in trades:
        assert trade.entry_price > 0
        assert trade.exit_price > 0
        assert trade.exit_time.value >= trade.entry_time.value
