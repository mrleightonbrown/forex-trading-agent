"""FX-19: mean reversion strategy tests.

The engineered series below is hand-derived (independently, via a
separate scratch calculation, not by running the implementation) using
period=5: a single +5 spike at index 5 in an otherwise flat 100-series
gives a *population* z-score of exactly 2 for that bar (mean=101,
stddev=2) — the entry_threshold's own default value, so it fires SHORT.
One bar later, as the spike leaves the "last element" position but stays
in the window, z becomes exactly -0.5 for every bar until the window
fully clears it — the sign flip from +2 to -0.5 is a zero-crossing, so
it fires FLAT immediately after the SHORT. The window then goes fully
flat again (z undefined, var=0) before a symmetric -5 dip at index 12
mirrors the whole story for a LONG entry and its own FLAT close.

closes = [100]*5 + [105] + [100]*6 + [95] + [100]*6

  index  5: z =  2    -> SHORT  (overbought)
  index  6: z = -0.5  -> FLAT   (crossed from +2 to -0.5)
  index  7: z = -0.5  -> None   (holding, no crossing, not extreme)
  index 10: z = None  -> None   (window fully flat again, var=0)
  index 12: z = -2    -> LONG   (oversold)
  index 13: z =  0.5  -> FLAT   (crossed from -2 to +0.5)
  index 14: z =  0.5  -> None   (holding, no crossing, not extreme)
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.strategies.mean_reversion import MeanReversionStrategy
from forex_agent.domain.target_position import TargetPosition
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trade_hypothesis import params_from_dict

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


def _candles(prices: list[int]) -> list[Candle]:
    return [_flat_candle(i, p) for i, p in enumerate(prices)]


# --- constructor validation -------------------------------------------------


def test_default_parameters() -> None:
    strategy = MeanReversionStrategy()

    assert strategy.period == 20
    assert strategy.entry_threshold == Decimal("2.0")
    assert strategy.strategy_version == "1"


def test_strategy_key_is_a_class_constant() -> None:
    assert MeanReversionStrategy.strategy_key == "mean_reversion_v1"


def test_rejects_non_int_period() -> None:
    with pytest.raises(TypeError, match="period"):
        MeanReversionStrategy(period=20.5)  # type: ignore[arg-type]


def test_rejects_bool_period() -> None:
    with pytest.raises(TypeError, match="period"):
        MeanReversionStrategy(period=True)


def test_rejects_period_below_two() -> None:
    with pytest.raises(ValueError, match="period"):
        MeanReversionStrategy(period=1)


def test_rejects_float_entry_threshold() -> None:
    with pytest.raises(TypeError, match="entry_threshold"):
        MeanReversionStrategy(entry_threshold=2.0)  # type: ignore[arg-type]


def test_rejects_non_decimal_entry_threshold() -> None:
    with pytest.raises(TypeError, match="entry_threshold"):
        MeanReversionStrategy(entry_threshold="2.0")  # type: ignore[arg-type]


def test_rejects_negative_entry_threshold() -> None:
    with pytest.raises(ValueError, match="entry_threshold"):
        MeanReversionStrategy(entry_threshold=Decimal("-0.01"))


# --- evaluate() ---------------------------------------------------------


def test_evaluate_returns_none_with_insufficient_data() -> None:
    strategy = MeanReversionStrategy(period=5)
    candles = _candles(_REVERSION_PRICES[:5])  # need period + 1 = 6

    assert strategy.evaluate(candles) is None


def test_evaluate_returns_none_with_zero_variance_window() -> None:
    strategy = MeanReversionStrategy(period=5)
    candles = _candles(_REVERSION_PRICES[:11])  # window is all 100s again

    assert strategy.evaluate(candles) is None


def test_evaluate_fires_short_when_overbought() -> None:
    strategy = MeanReversionStrategy(period=5)
    candles = _candles(_REVERSION_PRICES[:6])  # through index 5, z == 2

    hypothesis = strategy.evaluate(candles)

    assert hypothesis is not None
    assert hypothesis.target_position is TargetPosition.SHORT
    assert hypothesis.instrument == EUR_USD
    assert hypothesis.generated_at == _ts(5)
    assert hypothesis.timeframe is Granularity.M1
    assert hypothesis.strategy_key == "mean_reversion_v1"
    assert hypothesis.strategy_version == "1"
    assert hypothesis.parameters == params_from_dict(
        {"period": 5, "entry_threshold": Decimal("2.0")}
    )
    assert "overbought" in hypothesis.rationale


def test_evaluate_fires_flat_on_crossing_after_short() -> None:
    strategy = MeanReversionStrategy(period=5)
    candles = _candles(_REVERSION_PRICES[:7])  # through index 6, z == -0.5

    hypothesis = strategy.evaluate(candles)

    assert hypothesis is not None
    assert hypothesis.target_position is TargetPosition.FLAT
    assert hypothesis.generated_at == _ts(6)
    assert "reverted through the mean" in hypothesis.rationale


def test_evaluate_holds_with_no_crossing_and_no_extreme() -> None:
    strategy = MeanReversionStrategy(period=5)
    candles = _candles(_REVERSION_PRICES[:8])  # through index 7, z == -0.5 again

    assert strategy.evaluate(candles) is None


def test_evaluate_fires_long_when_oversold() -> None:
    strategy = MeanReversionStrategy(period=5)
    candles = _candles(_REVERSION_PRICES[:13])  # through index 12, z == -2

    hypothesis = strategy.evaluate(candles)

    assert hypothesis is not None
    assert hypothesis.target_position is TargetPosition.LONG
    assert hypothesis.generated_at == _ts(12)
    assert "oversold" in hypothesis.rationale


def test_evaluate_fires_flat_on_crossing_after_long() -> None:
    strategy = MeanReversionStrategy(period=5)
    candles = _candles(_REVERSION_PRICES[:14])  # through index 13, z == 0.5

    hypothesis = strategy.evaluate(candles)

    assert hypothesis is not None
    assert hypothesis.target_position is TargetPosition.FLAT
    assert hypothesis.generated_at == _ts(13)


def test_evaluate_holds_with_no_crossing_and_no_extreme_after_long() -> None:
    strategy = MeanReversionStrategy(period=5)
    candles = _candles(_REVERSION_PRICES[:15])  # through index 14, z == 0.5 again

    assert strategy.evaluate(candles) is None
