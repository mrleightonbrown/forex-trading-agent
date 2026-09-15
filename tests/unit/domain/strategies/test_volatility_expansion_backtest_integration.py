"""FX-20: VolatilityExpansionBreakoutStrategy run through the actual
backtest engine (FX-10) and trade simulator, including FLAT-closes-
without-reopening (FX-18) end to end, not just called directly.

Same engineered series as test_volatility_expansion.py: with
short_period=2, long_period=5, breakout_lookback=3,
expansion_threshold=1.5, LONG fires at index 6, FLAT at index 8, SHORT
at index 16, FLAT at index 17.

Hand-traced through the pipeline (open equals close on every bar in this
series, zero spread, so entry/exit prices are just the relevant bar's
price):
- LONG (index 6) executes at index 7's open = 100.5.
- FLAT (index 8) closes it at index 9's open = 100.5 -- both land on the
  series' quiet plateau, so this trade's pnl is coincidentally 0. This
  test verifies ordering/timing/FLAT-close-without-reopen, not P&L
  magnitude (already covered by FX-11H's own tests) -- same reasoning as
  FX-19's own backtest-integration test.
- SHORT (index 16) executes at index 17's open = 100.5.
- FLAT (index 17) closes it at index 18's open = 100.5, again pnl 0.
- Critically: only 2 trades come out of 4 hypotheses -- FLAT must not
  reopen a position.
"""

from datetime import UTC, datetime
from decimal import Decimal

from forex_agent.domain.backtest import run_backtest
from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.strategies.volatility_expansion import VolatilityExpansionBreakoutStrategy
from forex_agent.domain.target_position import TargetPosition
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trade_side import TradeSide
from forex_agent.domain.trade_simulation import simulate_trades

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")

_QUIET = (Decimal(101), Decimal(100), Decimal("100.5"))
_VOLATILITY_BARS = (
    [_QUIET] * 6
    + [(Decimal(140), Decimal(80), Decimal(105))]
    + [_QUIET] * 2
    + [_QUIET] * 3
    + [(Decimal("102.2"), Decimal("100.5"), Decimal(102))]
    + [_QUIET] * 3
    + [(Decimal(120), Decimal(60), Decimal(96))]
    + [_QUIET] * 2
    + [_QUIET] * 3
)


def _ts(minute: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, 0, minute, 0, tzinfo=UTC))


def _candle(minute: int, high: Decimal, low: Decimal, close: Decimal) -> Candle:
    bar = Ohlc(open=close, high=high, low=low, close=close)
    return Candle(
        instrument=EUR_USD,
        granularity=Granularity.M1,
        start_time=_ts(minute),
        bid=bar,
        ask=bar,
        volume=1,
        is_finalized=True,
    )


def _make_candles() -> list[Candle]:
    return [_candle(i, high, low, close) for i, (high, low, close) in enumerate(_VOLATILITY_BARS)]


def _strategy() -> VolatilityExpansionBreakoutStrategy:
    return VolatilityExpansionBreakoutStrategy(
        short_period=2, long_period=5, breakout_lookback=3, expansion_threshold=Decimal("1.5")
    )


def test_run_backtest_fires_long_flat_short_flat_in_order() -> None:
    hypotheses = run_backtest(_strategy(), _make_candles())

    assert [(h.target_position, h.generated_at) for h in hypotheses] == [
        (TargetPosition.LONG, _ts(6)),
        (TargetPosition.FLAT, _ts(8)),
        (TargetPosition.SHORT, _ts(16)),
        (TargetPosition.FLAT, _ts(17)),
    ]


def test_simulate_trades_closes_without_reopening_on_flat() -> None:
    candles = _make_candles()

    hypotheses = run_backtest(_strategy(), candles)
    trades = simulate_trades(hypotheses, candles)

    # 4 hypotheses (LONG, FLAT, SHORT, FLAT) but only 2 trades -- FLAT
    # closes, it never opens a new position.
    assert len(trades) == 2
    first, second = trades

    assert first.side is TradeSide.LONG
    assert first.entry_price == Decimal("100.5")
    assert first.entry_time == _ts(7)
    assert first.exit_price == Decimal("100.5")
    assert first.exit_time == _ts(9)
    assert first.pnl.amount == Decimal(0)

    assert second.side is TradeSide.SHORT
    assert second.entry_price == Decimal("100.5")
    assert second.entry_time == _ts(17)
    assert second.exit_price == Decimal("100.5")
    assert second.exit_time == _ts(18)
    assert second.pnl.amount == Decimal(0)
