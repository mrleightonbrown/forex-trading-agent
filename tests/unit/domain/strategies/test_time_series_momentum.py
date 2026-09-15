"""FX-16: time-series momentum strategy tests.

The engineered series below is hand-computed: with lookback=3,
threshold=0, closes = [100, 100, 100, 100, 110, 121, 100, 99] produce no
signal at index 3 (return=0, at the boundary), LONG at index 4
(return=0.10), a repeat LONG at index 5 (return=0.21), no signal again at
index 6 (return=0, boundary), and SHORT at index 7 (return=-0.10).
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.strategies.time_series_momentum import TimeSeriesMomentumStrategy
from forex_agent.domain.target_position import TargetPosition
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trade_hypothesis import params_from_dict

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")

_MOMENTUM_PRICES = [100, 100, 100, 100, 110, 121, 100, 99]


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


def test_default_parameters() -> None:
    strategy = TimeSeriesMomentumStrategy()

    assert strategy.lookback == 20
    assert strategy.threshold == Decimal("0")
    assert strategy.strategy_version == "1"


def test_strategy_key_is_a_class_constant() -> None:
    assert TimeSeriesMomentumStrategy.strategy_key == "time_series_momentum_v1"


def test_rejects_non_int_lookback() -> None:
    with pytest.raises(TypeError, match="lookback"):
        TimeSeriesMomentumStrategy(lookback=20.5)  # type: ignore[arg-type]


def test_rejects_bool_lookback() -> None:
    with pytest.raises(TypeError, match="lookback"):
        TimeSeriesMomentumStrategy(lookback=True)


def test_rejects_lookback_below_one() -> None:
    with pytest.raises(ValueError, match="lookback"):
        TimeSeriesMomentumStrategy(lookback=0)


def test_rejects_float_threshold() -> None:
    with pytest.raises(TypeError, match="threshold"):
        TimeSeriesMomentumStrategy(threshold=0.01)  # type: ignore[arg-type]


def test_rejects_non_decimal_threshold() -> None:
    with pytest.raises(TypeError, match="threshold"):
        TimeSeriesMomentumStrategy(threshold="0.01")  # type: ignore[arg-type]


def test_rejects_negative_threshold() -> None:
    with pytest.raises(ValueError, match="threshold"):
        TimeSeriesMomentumStrategy(threshold=Decimal("-0.01"))


# --- evaluate() ---------------------------------------------------------


def test_evaluate_returns_none_with_insufficient_data() -> None:
    strategy = TimeSeriesMomentumStrategy(lookback=3, threshold=Decimal("0"))
    candles = _candles(_MOMENTUM_PRICES[:3])  # need lookback + 1 = 4

    assert strategy.evaluate(candles) is None


def test_evaluate_returns_none_at_zero_return_with_zero_threshold() -> None:
    strategy = TimeSeriesMomentumStrategy(lookback=3, threshold=Decimal("0"))
    candles = _candles(_MOMENTUM_PRICES[:4])  # return == 0, not > 0

    assert strategy.evaluate(candles) is None


def test_evaluate_fires_long_above_threshold() -> None:
    strategy = TimeSeriesMomentumStrategy(lookback=3, threshold=Decimal("0"))
    candles = _candles(_MOMENTUM_PRICES[:5])  # return = 0.10

    hypothesis = strategy.evaluate(candles)

    assert hypothesis is not None
    assert hypothesis.target_position is TargetPosition.LONG
    assert hypothesis.instrument == EUR_USD
    assert hypothesis.generated_at == _ts(4)
    assert hypothesis.timeframe is Granularity.M1
    assert hypothesis.strategy_key == "time_series_momentum_v1"
    assert hypothesis.strategy_version == "1"
    assert hypothesis.parameters == params_from_dict({"lookback": 3, "threshold": Decimal("0")})
    assert "exceeds" in hypothesis.rationale


def test_evaluate_fires_long_again_while_momentum_continues() -> None:
    strategy = TimeSeriesMomentumStrategy(lookback=3, threshold=Decimal("0"))
    candles = _candles(_MOMENTUM_PRICES[:6])  # return = 0.21

    hypothesis = strategy.evaluate(candles)

    assert hypothesis is not None
    assert hypothesis.target_position is TargetPosition.LONG
    assert hypothesis.generated_at == _ts(5)


def test_evaluate_returns_none_again_at_zero_return() -> None:
    strategy = TimeSeriesMomentumStrategy(lookback=3, threshold=Decimal("0"))
    candles = _candles(_MOMENTUM_PRICES[:7])  # return == 0 again

    assert strategy.evaluate(candles) is None


def test_evaluate_fires_short_below_negative_threshold() -> None:
    strategy = TimeSeriesMomentumStrategy(lookback=3, threshold=Decimal("0"))
    candles = _candles(_MOMENTUM_PRICES[:8])  # return = -0.10

    hypothesis = strategy.evaluate(candles)

    assert hypothesis is not None
    assert hypothesis.target_position is TargetPosition.SHORT
    assert hypothesis.generated_at == _ts(7)
    assert "below" in hypothesis.rationale


def test_deadband_suppresses_a_signal_that_would_otherwise_fire() -> None:
    # Same series, but with a 0.15 deadband the +0.10 return at index 4
    # no longer clears the threshold.
    strategy = TimeSeriesMomentumStrategy(lookback=3, threshold=Decimal("0.15"))
    candles = _candles(_MOMENTUM_PRICES[:5])

    assert strategy.evaluate(candles) is None


def test_deadband_still_allows_a_large_enough_return() -> None:
    # The +0.21 return at index 5 clears a 0.15 deadband.
    strategy = TimeSeriesMomentumStrategy(lookback=3, threshold=Decimal("0.15"))
    candles = _candles(_MOMENTUM_PRICES[:6])

    hypothesis = strategy.evaluate(candles)

    assert hypothesis is not None
    assert hypothesis.target_position is TargetPosition.LONG
