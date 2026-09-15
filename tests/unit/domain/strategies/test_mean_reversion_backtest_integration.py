"""FX-19: MeanReversionStrategy run through the actual backtest engine
(FX-10) and trade simulator, including FX-18's FLAT-closes-without-
reopening behavior end to end, not just called directly.

Same engineered series as test_mean_reversion.py: with period=5,
closes = [100]*5 + [105] + [100]*6 + [95] + [100]*6 produce SHORT at
index 5, FLAT at index 6, LONG at index 12, FLAT at index 13.

Hand-traced through the pipeline (flat/zero-spread candles, so entry and
exit prices are just the relevant bar's price):
- SHORT (index 5) executes at index 6's open = 100.
- FLAT (index 6) closes it at index 7's open = 100 -- both the SHORT's
  entry and exit land on the series' "back to 100" plateau, so this
  trade's pnl is coincidentally 0. That's fine: this test verifies
  ordering/timing/FLAT-close-without-reopen, not P&L magnitude (already
  covered by FX-11H's own tests).
- LONG (index 12) executes at index 13's open = 100, mirroring the SHORT.
- FLAT (index 13) closes it at index 14's open = 100, again pnl 0.
- Critically: only 2 trades come out of 4 hypotheses -- FLAT must not
  reopen a position, unlike a same-direction or opposite-direction
  LONG/SHORT hypothesis would.
"""

from datetime import UTC, datetime
from decimal import Decimal

from forex_agent.domain.backtest import run_backtest
from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.strategies.mean_reversion import MeanReversionStrategy
from forex_agent.domain.target_position import TargetPosition
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trade_side import TradeSide
from forex_agent.domain.trade_simulation import simulate_trades

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")
_REVERSION_PRICES = [100] * 5 + [105] + [100] * 6 + [95] + [100] * 6


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
    return [_flat_candle(i, p) for i, p in enumerate(_REVERSION_PRICES)]


def test_run_backtest_fires_short_flat_long_flat_in_order() -> None:
    strategy = MeanReversionStrategy(period=5)

    hypotheses = run_backtest(strategy, _make_candles())

    assert [(h.target_position, h.generated_at) for h in hypotheses] == [
        (TargetPosition.SHORT, _ts(5)),
        (TargetPosition.FLAT, _ts(6)),
        (TargetPosition.LONG, _ts(12)),
        (TargetPosition.FLAT, _ts(13)),
    ]


def test_simulate_trades_closes_without_reopening_on_flat() -> None:
    strategy = MeanReversionStrategy(period=5)
    candles = _make_candles()

    hypotheses = run_backtest(strategy, candles)
    trades = simulate_trades(hypotheses, candles)

    # 4 hypotheses (SHORT, FLAT, LONG, FLAT) but only 2 trades -- FLAT
    # closes, it never opens a new position.
    assert len(trades) == 2
    first, second = trades

    assert first.side is TradeSide.SHORT
    assert first.entry_price == Decimal(100)
    assert first.entry_time == _ts(6)
    assert first.exit_price == Decimal(100)
    assert first.exit_time == _ts(7)
    assert first.pnl.amount == Decimal(0)

    assert second.side is TradeSide.LONG
    assert second.entry_price == Decimal(100)
    assert second.entry_time == _ts(13)
    assert second.exit_price == Decimal(100)
    assert second.exit_time == _ts(14)
    assert second.pnl.amount == Decimal(0)
