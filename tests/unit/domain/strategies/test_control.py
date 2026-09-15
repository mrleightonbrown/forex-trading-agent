"""FX-22: control strategy tests."""

from datetime import UTC, datetime
from decimal import Decimal

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
from forex_agent.domain.target_position import TargetPosition
from forex_agent.domain.timestamps import UtcTimestamp

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


# --- AlwaysLongStrategy ------------------------------------------------


def test_always_long_fires_long_on_every_bar() -> None:
    strategy = AlwaysLongStrategy()
    for length in range(1, 4):
        hypothesis = strategy.evaluate(_candles([100] * length))
        assert hypothesis is not None
        assert hypothesis.target_position is TargetPosition.LONG
        assert hypothesis.strategy_key == "always_long_v1"
        assert hypothesis.rationale


def test_always_long_returns_none_for_empty_candles() -> None:
    assert AlwaysLongStrategy().evaluate([]) is None


# --- AlwaysShortStrategy -------------------------------------------------


def test_always_short_fires_short_on_every_bar() -> None:
    strategy = AlwaysShortStrategy()
    hypothesis = strategy.evaluate(_candles([100]))

    assert hypothesis is not None
    assert hypothesis.target_position is TargetPosition.SHORT
    assert hypothesis.strategy_key == "always_short_v1"


def test_always_short_returns_none_for_empty_candles() -> None:
    assert AlwaysShortStrategy().evaluate([]) is None


# --- PreviousBarDirectionStrategy -----------------------------------------


def test_previous_bar_direction_returns_none_with_fewer_than_two_candles() -> None:
    strategy = PreviousBarDirectionStrategy()

    assert strategy.evaluate([]) is None
    assert strategy.evaluate(_candles([100])) is None


def test_previous_bar_direction_fires_long_when_close_rises() -> None:
    strategy = PreviousBarDirectionStrategy()

    hypothesis = strategy.evaluate(_candles([100, 101]))

    assert hypothesis is not None
    assert hypothesis.target_position is TargetPosition.LONG
    assert hypothesis.strategy_key == "previous_bar_direction_v1"
    assert "up" in hypothesis.rationale


def test_previous_bar_direction_fires_short_when_close_falls() -> None:
    strategy = PreviousBarDirectionStrategy()

    hypothesis = strategy.evaluate(_candles([101, 100]))

    assert hypothesis is not None
    assert hypothesis.target_position is TargetPosition.SHORT
    assert "down" in hypothesis.rationale


def test_previous_bar_direction_returns_none_when_close_is_unchanged() -> None:
    strategy = PreviousBarDirectionStrategy()

    assert strategy.evaluate(_candles([100, 100])) is None


# --- NoTradeStrategy -------------------------------------------------------


def test_no_trade_always_returns_none() -> None:
    strategy = NoTradeStrategy()

    assert strategy.evaluate([]) is None
    assert strategy.evaluate(_candles([100])) is None
    assert strategy.evaluate(_candles([100, 200, 50])) is None
