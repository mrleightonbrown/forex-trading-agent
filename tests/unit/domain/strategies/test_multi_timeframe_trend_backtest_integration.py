"""FX-25: MultiTimeframeTrendStrategy run through the actual backtest
engine (FX-10) and trade simulator, including FLAT-closes-without-
reopening (FX-18) end to end, not just called directly.

Same engineered series as test_multi_timeframe_trend.py: LONG (confirmed)
at H1 hour 19, FLAT (unconfirmed SHORT) at hour 22, LONG (confirmed)
again at hour 26, SHORT (confirmed, H4 now bearish) at hour 32.

Hand-traced through the pipeline (flat/zero-spread H1 candles, so entry
and exit prices are just the relevant bar's price):
- LONG (hour 19) executes at hour 20's open = 120.
- FLAT (hour 22) closes it at hour 23's open = 90. pnl = 90 - 120 = -30.
- LONG (hour 26) executes at hour 27's open = 110 (a genuinely fresh
  entry -- FLAT does not reopen, FX-18).
- SHORT (hour 32) closes the LONG at hour 33's open = 90
  (reversal; pnl = 90 - 110 = -20) and opens SHORT at the same price.
- End of data (hour 34, last candle): the open SHORT is force-closed at
  the last candle's close = 80. pnl = 90 - 80 = 10.
- Critically: 4 hypotheses (LONG, FLAT, LONG, SHORT) produce 3 trades --
  FLAT closes without reopening.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from forex_agent.domain.backtest import run_backtest
from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.strategies.multi_timeframe_trend import MultiTimeframeTrendStrategy
from forex_agent.domain.target_position import TargetPosition
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trade_side import TradeSide
from forex_agent.domain.trade_simulation import simulate_trades

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")

_H1_CLOSES = [100] * 16 + [
    100,
    100,
    100,
    110,
    120,
    130,
    100,
    90,
    80,
    90,
    100,
    110,
    120,
    130,
    140,
    150,
    100,
    90,
    80,
]
_H4_CLOSES = [100, 102, 104, 106, 108, 110, 105, 95, 85, 75, 70, 65]

_EPOCH = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


def _h1_ts(hour: int) -> UtcTimestamp:
    return UtcTimestamp(_EPOCH + timedelta(hours=hour))


def _flat_candle(start: UtcTimestamp, granularity: Granularity, price: int) -> Candle:
    p = Decimal(price)
    flat = Ohlc(open=p, high=p, low=p, close=p)
    return Candle(
        instrument=EUR_USD,
        granularity=granularity,
        start_time=start,
        bid=flat,
        ask=flat,
        volume=1,
        is_finalized=True,
    )


def _h1_candles() -> list[Candle]:
    return [_flat_candle(_h1_ts(h), Granularity.H1, _H1_CLOSES[h]) for h in range(len(_H1_CLOSES))]


def _h4_candles() -> list[Candle]:
    return [
        _flat_candle(_h1_ts(4 * k), Granularity.H4, _H4_CLOSES[k]) for k in range(len(_H4_CLOSES))
    ]


def _strategy() -> MultiTimeframeTrendStrategy:
    return MultiTimeframeTrendStrategy(
        h4_candles=_h4_candles(),
        h1_fast_period=2,
        h1_slow_period=3,
        h4_fast_period=2,
        h4_slow_period=3,
    )


def test_run_backtest_fires_long_flat_long_short_in_order() -> None:
    hypotheses = run_backtest(_strategy(), _h1_candles())

    assert [(h.target_position, h.generated_at) for h in hypotheses] == [
        (TargetPosition.LONG, _h1_ts(19)),
        (TargetPosition.FLAT, _h1_ts(22)),
        (TargetPosition.LONG, _h1_ts(26)),
        (TargetPosition.SHORT, _h1_ts(32)),
    ]


def test_simulate_trades_closes_without_reopening_on_flat() -> None:
    candles = _h1_candles()

    hypotheses = run_backtest(_strategy(), candles)
    trades = simulate_trades(hypotheses, candles)

    # 4 hypotheses but only 3 trades -- FLAT closes, it never reopens.
    assert len(trades) == 3
    first, second, third = trades

    assert first.side is TradeSide.LONG
    assert first.entry_price == Decimal(120)
    assert first.entry_time == _h1_ts(20)
    assert first.exit_price == Decimal(90)
    assert first.exit_time == _h1_ts(23)
    assert first.pnl.amount == Decimal(90 - 120)

    assert second.side is TradeSide.LONG
    assert second.entry_price == Decimal(110)
    assert second.entry_time == _h1_ts(27)
    assert second.exit_price == Decimal(90)
    assert second.exit_time == _h1_ts(33)
    assert second.pnl.amount == Decimal(90 - 110)

    assert third.side is TradeSide.SHORT
    assert third.entry_price == Decimal(90)
    assert third.entry_time == _h1_ts(33)
    # still open at the end -> force-closed at the last candle's close
    assert third.exit_price == Decimal(80)
    assert third.exit_time == _h1_ts(34)
    assert third.pnl.amount == Decimal(90 - 80)
