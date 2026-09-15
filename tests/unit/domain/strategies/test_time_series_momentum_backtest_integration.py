"""FX-16: TimeSeriesMomentumStrategy run through the actual backtest
engine (FX-10) and trade simulator (FX-11H), not just called directly.

With lookback=3, threshold=0, closes =
[100, 100, 100, 100, 110, 121, 100, 99, 95, 90] produce LONG at index 4,
a repeat LONG at index 5, SHORT at index 7, a repeat SHORT at index 8,
and another SHORT at index 9 — but index 9 is the *final* candle, so
FX-11H's rule makes it not actionable (no next bar to execute from).

Hand-traced through the pipeline:
- LONG (index 4) executes at index 5's open = 121.
- Repeat LONG (index 5) is a same-direction no-op.
- SHORT (index 7) closes the LONG and opens SHORT at index 8's open = 95
  (a reversal spanning two different candles, unlike FX-15's degenerate
  same-candle case).
- Repeat SHORT (index 8) is a same-direction no-op.
- SHORT (index 9) is generated on the final candle: dropped, not
  actionable.
- End of data: the open SHORT (entered at 95) is force-closed using the
  last candle (index 9)'s close = 90.
"""

from datetime import UTC, datetime
from decimal import Decimal

from forex_agent.domain.backtest import run_backtest
from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.strategies.time_series_momentum import TimeSeriesMomentumStrategy
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trade_side import TradeSide
from forex_agent.domain.trade_simulation import simulate_trades

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")
_MOMENTUM_PRICES = [100, 100, 100, 100, 110, 121, 100, 99, 95, 90]


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


def _make_candles() -> list[Candle]:
    return [_flat_candle(i, p) for i, p in enumerate(_MOMENTUM_PRICES)]


def test_run_backtest_fires_at_every_qualifying_bar() -> None:
    strategy = TimeSeriesMomentumStrategy(lookback=3, threshold=Decimal("0"))

    hypotheses = run_backtest(strategy, _make_candles())

    assert [(h.side, h.generated_at) for h in hypotheses] == [
        (TradeSide.LONG, _ts(4)),
        (TradeSide.LONG, _ts(5)),
        (TradeSide.SHORT, _ts(7)),
        (TradeSide.SHORT, _ts(8)),
        (TradeSide.SHORT, _ts(9)),
    ]


def test_simulate_trades_produces_correct_round_trip() -> None:
    strategy = TimeSeriesMomentumStrategy(lookback=3, threshold=Decimal("0"))
    candles = _make_candles()

    hypotheses = run_backtest(strategy, candles)
    trades = simulate_trades(hypotheses, candles)

    # The final SHORT (index 9) was generated on the last candle and is
    # not actionable, so only 2 trades come out despite 5 hypotheses.
    assert len(trades) == 2
    first, second = trades

    assert first.side is TradeSide.LONG
    assert first.entry_price == Decimal(121)
    assert first.entry_time == _ts(5)
    assert first.exit_price == Decimal(95)
    assert first.exit_time == _ts(8)
    assert first.pnl.amount == Decimal(95 - 121)

    assert second.side is TradeSide.SHORT
    assert second.entry_price == Decimal(95)
    assert second.entry_time == _ts(8)
    assert second.exit_price == Decimal(90)
    assert second.exit_time == _ts(9)
    assert second.pnl.amount == Decimal(95 - 90)
