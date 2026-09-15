"""FX-14: EmaCrossoverStrategy run through the actual backtest engine
(FX-10) and trade simulator (FX-11H), not just called directly — proves
the strategy behaves correctly inside the real pipeline, not only in
isolation.
"""

from datetime import UTC, datetime
from decimal import Decimal

from forex_agent.domain.backtest import run_backtest
from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.strategies.ema_crossover import EmaCrossoverStrategy
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trade_side import TradeSide
from forex_agent.domain.trade_simulation import simulate_trades

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")

# Same engineered series as test_ema_crossover.py: one clean bullish cross
# at index 4, one clean bearish cross at index 7 (fast=2, slow=3).
_CROSSOVER_PRICES = [100, 100, 100, 100, 110, 120, 130, 100, 90, 80]


def _ts(minute: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, 0, minute, 0, tzinfo=UTC))


def _flat_candle(minute: int, price: int) -> Candle:
    p = Decimal(price)
    flat = Ohlc(open=p, high=p, low=p, close=p)
    return Candle(
        instrument=EUR_USD,
        granularity=Granularity.M1,
        start_time=_ts(minute),
        bid=flat,
        ask=flat,
        volume=1,
        is_finalized=True,
    )


def test_run_backtest_produces_exactly_the_two_engineered_crosses() -> None:
    candles = [_flat_candle(i, p) for i, p in enumerate(_CROSSOVER_PRICES)]
    strategy = EmaCrossoverStrategy(fast_period=2, slow_period=3)

    hypotheses = run_backtest(strategy, candles)

    assert len(hypotheses) == 2
    long_hyp, short_hyp = hypotheses
    assert long_hyp.side is TradeSide.LONG
    assert long_hyp.generated_at == _ts(4)
    assert short_hyp.side is TradeSide.SHORT
    assert short_hyp.generated_at == _ts(7)


def test_simulate_trades_produces_correct_round_trip() -> None:
    candles = [_flat_candle(i, p) for i, p in enumerate(_CROSSOVER_PRICES)]
    strategy = EmaCrossoverStrategy(fast_period=2, slow_period=3)

    hypotheses = run_backtest(strategy, candles)
    trades = simulate_trades(hypotheses, candles)

    assert len(trades) == 2
    first, second = trades
    # Long hypothesis at index 4 executes at index 5's open (zero spread
    # here, so open == close == price).
    assert first.side is TradeSide.LONG
    assert first.entry_price == Decimal(120)
    assert first.entry_time == _ts(5)
    # Reversal: short hypothesis at index 7 closes the long and opens the
    # short at index 8's open.
    assert first.exit_price == Decimal(90)
    assert first.exit_time == _ts(8)
    assert second.side is TradeSide.SHORT
    assert second.entry_price == Decimal(90)
    assert second.entry_time == _ts(8)
    # Still open at the end -> force-closed at the last candle's close.
    assert second.exit_price == Decimal(80)
    assert second.exit_time == _ts(9)
