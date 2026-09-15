"""FX-15: close-channel breakout strategy tests.

The engineered series below is hand-computed: with lookback=3, closes
= [100, 101, 99, 100, 105, 106, 90, 80] produce no signal at index 3
(100 is within [99, 101]), LONG at index 4 (105 > rolling max 101), a
repeat LONG at index 5 (106 > rolling max 105), SHORT at index 6
(90 < rolling min 100), and a repeat SHORT at index 7 (80 < rolling
min 90).
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.strategies.close_channel_breakout import CloseChannelBreakoutStrategy
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trade_hypothesis import params_from_dict
from forex_agent.domain.trade_side import TradeSide

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")

_BREAKOUT_PRICES = [100, 101, 99, 100, 105, 106, 90, 80]
_TIE_PRICES = [100, 101, 99, 101]


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


# --- constructor validation -------------------------------------------------


def test_default_lookback() -> None:
    strategy = CloseChannelBreakoutStrategy()

    assert strategy.lookback == 20
    assert strategy.strategy_version == "1"


def test_strategy_key_is_a_class_constant() -> None:
    assert CloseChannelBreakoutStrategy.strategy_key == "close_channel_breakout_v1"


def test_rejects_non_int_lookback() -> None:
    with pytest.raises(TypeError, match="lookback"):
        CloseChannelBreakoutStrategy(lookback=20.5)  # type: ignore[arg-type]


def test_rejects_bool_lookback() -> None:
    with pytest.raises(TypeError, match="lookback"):
        CloseChannelBreakoutStrategy(lookback=True)


def test_rejects_lookback_below_one() -> None:
    with pytest.raises(ValueError, match="lookback"):
        CloseChannelBreakoutStrategy(lookback=0)


# --- evaluate() ---------------------------------------------------------


def test_evaluate_returns_none_with_insufficient_data() -> None:
    strategy = CloseChannelBreakoutStrategy(lookback=3)
    candles = _candles(_BREAKOUT_PRICES[:3])  # need lookback + 1 = 4

    assert strategy.evaluate(candles) is None


def test_evaluate_returns_none_within_the_channel() -> None:
    strategy = CloseChannelBreakoutStrategy(lookback=3)
    candles = _candles(_BREAKOUT_PRICES[:4])  # current=100, within [99, 101]

    assert strategy.evaluate(candles) is None


def test_evaluate_returns_none_on_exact_tie() -> None:
    strategy = CloseChannelBreakoutStrategy(lookback=3)
    candles = _candles(_TIE_PRICES)  # current=101 == rolling max, not >

    assert strategy.evaluate(candles) is None


def test_evaluate_fires_long_on_breakout_above() -> None:
    strategy = CloseChannelBreakoutStrategy(lookback=3)
    candles = _candles(_BREAKOUT_PRICES[:5])  # through index 4

    hypothesis = strategy.evaluate(candles)

    assert hypothesis is not None
    assert hypothesis.side is TradeSide.LONG
    assert hypothesis.instrument == EUR_USD
    assert hypothesis.generated_at == _ts(4)
    assert hypothesis.timeframe is Granularity.M1
    assert hypothesis.strategy_key == "close_channel_breakout_v1"
    assert hypothesis.strategy_version == "1"
    assert hypothesis.parameters == params_from_dict({"lookback": 3})
    assert "above" in hypothesis.rationale


def test_evaluate_fires_long_again_while_breakout_continues() -> None:
    strategy = CloseChannelBreakoutStrategy(lookback=3)
    candles = _candles(_BREAKOUT_PRICES[:6])  # through index 5

    hypothesis = strategy.evaluate(candles)

    assert hypothesis is not None
    assert hypothesis.side is TradeSide.LONG
    assert hypothesis.generated_at == _ts(5)


def test_evaluate_fires_short_on_breakout_below() -> None:
    strategy = CloseChannelBreakoutStrategy(lookback=3)
    candles = _candles(_BREAKOUT_PRICES[:7])  # through index 6

    hypothesis = strategy.evaluate(candles)

    assert hypothesis is not None
    assert hypothesis.side is TradeSide.SHORT
    assert hypothesis.generated_at == _ts(6)
    assert "below" in hypothesis.rationale


def test_evaluate_fires_short_again_while_breakout_continues() -> None:
    strategy = CloseChannelBreakoutStrategy(lookback=3)
    candles = _candles(_BREAKOUT_PRICES[:8])  # through index 7

    hypothesis = strategy.evaluate(candles)

    assert hypothesis is not None
    assert hypothesis.side is TradeSide.SHORT
    assert hypothesis.generated_at == _ts(7)
