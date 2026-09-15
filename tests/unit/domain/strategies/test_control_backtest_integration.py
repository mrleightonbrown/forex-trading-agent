"""FX-22: control strategies run through the actual backtest engine
(FX-10) and trade simulator, proving the claimed baseline behavior end
to end, not just in evaluate() isolation.
"""

from datetime import UTC, datetime
from decimal import Decimal

from forex_agent.domain.backtest import run_backtest
from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.strategies.control import (
    AlwaysLongStrategy,
    AlwaysShortStrategy,
    NoTradeStrategy,
    PreviousBarDirectionStrategy,
)
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trade_side import TradeSide
from forex_agent.domain.trade_simulation import simulate_trades

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")


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


def _candles(prices: list[int]) -> list[Candle]:
    return [_flat_candle(i, p) for i, p in enumerate(prices)]


def test_always_long_produces_exactly_one_held_trade() -> None:
    """Buy-and-hold: fires LONG on every bar, but same-direction repeats
    (FX-11) collapse into one open position, force-closed at the end."""
    candles = _candles([100, 101, 102, 103, 104])

    hypotheses = run_backtest(AlwaysLongStrategy(), candles)
    assert len(hypotheses) == 5  # fires every bar

    trades = simulate_trades(hypotheses, candles)

    assert len(trades) == 1  # but only ever one position
    trade = trades[0]
    assert trade.side is TradeSide.LONG
    assert trade.entry_price == Decimal(101)  # bar 1's open (bar 0's signal, next-bar execution)
    assert trade.entry_time == _ts(1)
    assert trade.exit_price == Decimal(104)  # force-closed at the last candle's close
    assert trade.exit_time == _ts(4)
    assert trade.pnl.amount == Decimal(104 - 101)


def test_always_short_produces_exactly_one_held_trade() -> None:
    candles = _candles([100, 99, 98, 97, 96])

    hypotheses = run_backtest(AlwaysShortStrategy(), candles)
    assert len(hypotheses) == 5

    trades = simulate_trades(hypotheses, candles)

    assert len(trades) == 1
    trade = trades[0]
    assert trade.side is TradeSide.SHORT
    assert trade.entry_price == Decimal(99)
    assert trade.entry_time == _ts(1)
    assert trade.exit_price == Decimal(96)
    assert trade.exit_time == _ts(4)
    assert trade.pnl.amount == Decimal(99 - 96)


def test_no_trade_produces_zero_hypotheses_and_zero_trades() -> None:
    candles = _candles([100, 200, 50, 75])

    hypotheses = run_backtest(NoTradeStrategy(), candles)
    assert hypotheses == []

    trades = simulate_trades(hypotheses, candles)
    assert trades == []


def test_previous_bar_direction_flips_with_the_engineered_series() -> None:
    """closes = [100, 101, 100, 102, 101, 101]: up, down, up, down, flat
    -> LONG@1, SHORT@2, LONG@3, SHORT@4, no signal at 5 (unchanged close).
    """
    candles = _candles([100, 101, 100, 102, 101, 101])

    hypotheses = run_backtest(PreviousBarDirectionStrategy(), candles)
    assert [(h.target_position.name, h.generated_at) for h in hypotheses] == [
        ("LONG", _ts(1)),
        ("SHORT", _ts(2)),
        ("LONG", _ts(3)),
        ("SHORT", _ts(4)),
    ]

    trades = simulate_trades(hypotheses, candles)

    assert len(trades) == 4
    first, second, third, fourth = trades

    assert first.side is TradeSide.LONG
    assert first.entry_price == Decimal(100)  # bar 2's open
    assert first.entry_time == _ts(2)
    assert first.exit_price == Decimal(102)  # bar 3's open, reversal
    assert first.exit_time == _ts(3)
    assert first.pnl.amount == Decimal(102 - 100)

    assert second.side is TradeSide.SHORT
    assert second.entry_price == Decimal(102)
    assert second.entry_time == _ts(3)
    assert second.exit_price == Decimal(101)  # bar 4's open, reversal
    assert second.exit_time == _ts(4)
    assert second.pnl.amount == Decimal(102 - 101)

    assert third.side is TradeSide.LONG
    assert third.entry_price == Decimal(101)
    assert third.entry_time == _ts(4)
    assert third.exit_price == Decimal(101)  # bar 5's open, reversal
    assert third.exit_time == _ts(5)
    assert third.pnl.amount == Decimal(0)

    assert fourth.side is TradeSide.SHORT
    assert fourth.entry_price == Decimal(101)
    assert fourth.entry_time == _ts(5)
    # still open at the end -> force-closed at the last candle's close
    assert fourth.exit_price == Decimal(101)
    assert fourth.exit_time == _ts(5)
    assert fourth.pnl.amount == Decimal(0)
