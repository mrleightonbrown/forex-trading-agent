"""FX-15: CloseChannelBreakoutStrategy run through the actual backtest
engine (FX-10) and trade simulator (FX-11H), not just called directly.

Same engineered series as test_close_channel_breakout.py: with
lookback=3, closes = [100, 101, 99, 100, 105, 106, 90, 80] produce LONG
at index 4, a repeat (no-op) LONG at index 5, SHORT at index 6, and a
repeat (no-op) SHORT at index 7.

Hand-traced through the pipeline:
- LONG hypothesis (index 4) executes at index 5's open = 106.
- Repeat LONG (index 5) is a same-direction no-op.
- SHORT hypothesis (index 6) closes the LONG and opens SHORT at index 7's
  open = 80 (a reversal, both using the same execution candle's price).
- Repeat SHORT (index 7) is a same-direction no-op.
- End of data: the open SHORT is force-closed using the LAST candle
  (index 7)'s close = 80 — the same candle it just entered on, since the
  series ends there. entry_time == exit_time == minute 7.
"""

from datetime import UTC, datetime
from decimal import Decimal

from forex_agent.domain.backtest import run_backtest
from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.strategies.close_channel_breakout import CloseChannelBreakoutStrategy
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trade_side import TradeSide
from forex_agent.domain.trade_simulation import simulate_trades

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")
_BREAKOUT_PRICES = [100, 101, 99, 100, 105, 106, 90, 80]


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


def test_run_backtest_fires_at_breakout_and_repeat_bars() -> None:
    candles = [_flat_candle(i, p) for i, p in enumerate(_BREAKOUT_PRICES)]
    strategy = CloseChannelBreakoutStrategy(lookback=3)

    hypotheses = run_backtest(strategy, candles)

    assert len(hypotheses) == 4
    sides_and_times = [(h.side, h.generated_at) for h in hypotheses]
    assert sides_and_times == [
        (TradeSide.LONG, _ts(4)),
        (TradeSide.LONG, _ts(5)),
        (TradeSide.SHORT, _ts(6)),
        (TradeSide.SHORT, _ts(7)),
    ]


def test_simulate_trades_produces_correct_round_trip() -> None:
    candles = [_flat_candle(i, p) for i, p in enumerate(_BREAKOUT_PRICES)]
    strategy = CloseChannelBreakoutStrategy(lookback=3)

    hypotheses = run_backtest(strategy, candles)
    trades = simulate_trades(hypotheses, candles)

    assert len(trades) == 2
    first, second = trades

    assert first.side is TradeSide.LONG
    assert first.entry_price == Decimal(106)
    assert first.entry_time == _ts(5)
    assert first.exit_price == Decimal(80)
    assert first.exit_time == _ts(7)
    assert first.pnl.amount == Decimal(80 - 106)

    assert second.side is TradeSide.SHORT
    assert second.entry_price == Decimal(80)
    assert second.entry_time == _ts(7)
    # Force-closed at the end using the same final candle it entered on.
    assert second.exit_price == Decimal(80)
    assert second.exit_time == _ts(7)
    assert second.pnl.amount == Decimal(0)
