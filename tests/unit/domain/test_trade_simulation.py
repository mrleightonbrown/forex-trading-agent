from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.money import Money
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trade_hypothesis import TradeHypothesis
from forex_agent.domain.trade_side import TradeSide
from forex_agent.domain.trade_simulation import simulate_trades

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")


def _ts(minute: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, 0, minute, 0, tzinfo=UTC))


def _flat_ohlc(price: str) -> Ohlc:
    return Ohlc(open=Decimal(price), high=Decimal(price), low=Decimal(price), close=Decimal(price))


def _candle(minute: int, bid_close: str, ask_close: str) -> Candle:
    return Candle(
        instrument=EUR_USD,
        granularity=Granularity.M1,
        start_time=_ts(minute),
        bid=_flat_ohlc(bid_close),
        ask=_flat_ohlc(ask_close),
        volume=1,
        is_finalized=True,
    )


def _hypothesis(minute: int, side: TradeSide) -> TradeHypothesis:
    return TradeHypothesis(
        instrument=EUR_USD, side=side, generated_at=_ts(minute), rationale="test"
    )


def test_empty_candles_returns_empty_trades() -> None:
    assert simulate_trades([_hypothesis(0, TradeSide.LONG)], []) == []


def test_empty_hypotheses_returns_empty_trades() -> None:
    candles = [_candle(0, "1.1000", "1.1002")]
    assert simulate_trades([], candles) == []


def test_single_hypothesis_force_closed_at_end() -> None:
    candles = [_candle(0, "1.1000", "1.1002"), _candle(1, "1.1010", "1.1012")]
    hypotheses = [_hypothesis(0, TradeSide.LONG)]

    trades = simulate_trades(hypotheses, candles)

    assert len(trades) == 1
    trade = trades[0]
    assert trade.side is TradeSide.LONG
    assert trade.entry_price == Decimal("1.1002")  # long enters at ask of candle 0
    assert trade.entry_time == _ts(0)
    assert trade.exit_price == Decimal("1.1010")  # long exits at bid of last candle
    assert trade.exit_time == _ts(1)
    assert trade.pnl == Money(Decimal("1.1010") - Decimal("1.1002"), "USD")


def test_reversal_produces_two_trades() -> None:
    candles = [
        _candle(0, "1.1000", "1.1002"),
        _candle(1, "1.1010", "1.1012"),
        _candle(2, "1.1020", "1.1022"),
    ]
    hypotheses = [
        _hypothesis(0, TradeSide.LONG),
        _hypothesis(1, TradeSide.SHORT),  # closes the long, opens a short
    ]

    trades = simulate_trades(hypotheses, candles)

    assert len(trades) == 2
    first, second = trades
    assert first.side is TradeSide.LONG
    assert first.entry_price == Decimal("1.1002")
    assert first.exit_price == Decimal("1.1010")  # long exits at bid of candle 1
    assert first.exit_time == _ts(1)

    assert second.side is TradeSide.SHORT
    assert second.entry_price == Decimal("1.1010")  # short enters at bid of candle 1
    assert second.entry_time == _ts(1)
    assert second.exit_price == Decimal("1.1022")  # force-closed: short exits at ask of candle 2
    assert second.exit_time == _ts(2)


def test_same_direction_repeat_is_a_noop() -> None:
    candles = [
        _candle(0, "1.1000", "1.1002"),
        _candle(1, "1.1010", "1.1012"),
        _candle(2, "1.1020", "1.1022"),
    ]
    hypotheses = [
        _hypothesis(0, TradeSide.LONG),
        _hypothesis(1, TradeSide.LONG),  # already long: no-op
    ]

    trades = simulate_trades(hypotheses, candles)

    assert len(trades) == 1  # only the force-close at the end
    trade = trades[0]
    assert trade.entry_price == Decimal("1.1002")
    assert trade.entry_time == _ts(0)  # unchanged by the repeated signal
    assert trade.exit_price == Decimal("1.1020")  # bid of the last candle
    assert trade.exit_time == _ts(2)


def test_short_trade_profits_when_price_falls() -> None:
    candles = [_candle(0, "1.1000", "1.1002"), _candle(1, "1.0990", "1.0992")]
    hypotheses = [_hypothesis(0, TradeSide.SHORT)]

    trades = simulate_trades(hypotheses, candles)

    trade = trades[0]
    assert trade.entry_price == Decimal("1.1000")  # short enters at bid
    assert trade.exit_price == Decimal("1.0992")  # short exits at ask of last candle
    assert trade.pnl.amount == Decimal("1.1000") - Decimal("1.0992")
    assert trade.pnl.amount > 0


def test_long_trade_loses_when_price_falls() -> None:
    candles = [_candle(0, "1.1000", "1.1002"), _candle(1, "1.0990", "1.0992")]
    hypotheses = [_hypothesis(0, TradeSide.LONG)]

    trades = simulate_trades(hypotheses, candles)

    trade = trades[0]
    assert trade.pnl.amount < 0


def test_rejects_hypothesis_with_no_matching_candle() -> None:
    candles = [_candle(0, "1.1000", "1.1002")]
    hypotheses = [_hypothesis(5, TradeSide.LONG)]  # no candle at minute 5

    with pytest.raises(ValueError, match="does not match"):
        simulate_trades(hypotheses, candles)
