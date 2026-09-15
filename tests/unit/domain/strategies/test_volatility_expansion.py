"""FX-20: volatility expansion breakout strategy tests.

The engineered series below (short_period=2, long_period=5,
breakout_lookback=3, expansion_threshold=1.5) is hand-derived
(independently, via a separate scratch calculation, not by running the
implementation) as high/low/close triples on an otherwise-quiet
(high=101, low=100, close=100.5) baseline:

  index  6: a single wide burst bar (high=140, low=80, close=105) pushes
            the ATR ratio to 2.38 (>= 1.5) while the close (105) breaks
            above the quiet 3-bar Donchian high (101) -> LONG.
  index  7: ratio is still 1.58 (>= 1.5, still "expanding") but the
            Donchian window now includes the burst bar itself
            (high=140), so the close (100.5) is back inside the channel
            -> no fresh breakout -> None (hold: expanding, no breakout).
  index  8: ratio has decayed to 1.02 (< 1.5); the previous bar's ratio
            (1.58) was >= 1.5 -> the expansion just ended -> FLAT.
  index 12: after the window has fully reset to quiet, a moderate bar
            (high=102.2, low=100.5, close=102) breaks the quiet 3-bar
            Donchian high (101) but only produces a ratio of 0.42
            (< 1.5) -> a breakout with no expansion behind it -> None.
  index 16: a wide downward burst bar (high=120, low=60, close=96)
            pushes the ratio to 2.14 (>= 1.5) while the close (96) breaks
            below the quiet 3-bar Donchian low (100) -> SHORT.
  index 17: ratio has already decayed to 1.43 (< 1.5, short_period=2
            reacts fast); the previous bar's ratio (2.14) was >= 1.5 ->
            FLAT.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.strategies.volatility_expansion import VolatilityExpansionBreakoutStrategy
from forex_agent.domain.target_position import TargetPosition
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trade_hypothesis import params_from_dict

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")

_QUIET = (Decimal(101), Decimal(100), Decimal("100.5"))
_VOLATILITY_BARS = (
    [_QUIET] * 6
    + [(Decimal(140), Decimal(80), Decimal(105))]  # index 6: burst up
    + [_QUIET] * 2  # index 7, 8
    + [_QUIET] * 3  # index 9-11
    + [(Decimal("102.2"), Decimal("100.5"), Decimal(102))]  # index 12: mild, no expansion
    + [_QUIET] * 3  # index 13-15
    + [(Decimal(120), Decimal(60), Decimal(96))]  # index 16: burst down
    + [_QUIET] * 2  # index 17, 18
    + [_QUIET] * 3  # index 19-21
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


def _candles(bars: list[tuple[Decimal, Decimal, Decimal]]) -> list[Candle]:
    return [_candle(i, high, low, close) for i, (high, low, close) in enumerate(bars)]


def _strategy() -> VolatilityExpansionBreakoutStrategy:
    return VolatilityExpansionBreakoutStrategy(
        short_period=2, long_period=5, breakout_lookback=3, expansion_threshold=Decimal("1.5")
    )


# --- constructor validation -------------------------------------------------


def test_default_parameters() -> None:
    strategy = VolatilityExpansionBreakoutStrategy()

    assert strategy.short_period == 14
    assert strategy.long_period == 50
    assert strategy.breakout_lookback == 20
    assert strategy.expansion_threshold == Decimal("1.5")
    assert strategy.strategy_version == "1"


def test_strategy_key_is_a_class_constant() -> None:
    assert VolatilityExpansionBreakoutStrategy.strategy_key == "volatility_expansion_breakout_v1"


def test_rejects_non_int_short_period() -> None:
    with pytest.raises(TypeError, match="short_period"):
        VolatilityExpansionBreakoutStrategy(short_period=14.5)  # type: ignore[arg-type]


def test_rejects_bool_short_period() -> None:
    with pytest.raises(TypeError, match="short_period"):
        VolatilityExpansionBreakoutStrategy(short_period=True)


def test_rejects_non_int_long_period() -> None:
    with pytest.raises(TypeError, match="long_period"):
        VolatilityExpansionBreakoutStrategy(long_period=50.5)  # type: ignore[arg-type]


def test_rejects_bool_long_period() -> None:
    with pytest.raises(TypeError, match="long_period"):
        VolatilityExpansionBreakoutStrategy(long_period=True)


def test_rejects_non_int_breakout_lookback() -> None:
    with pytest.raises(TypeError, match="breakout_lookback"):
        VolatilityExpansionBreakoutStrategy(breakout_lookback=20.5)  # type: ignore[arg-type]


def test_rejects_bool_breakout_lookback() -> None:
    with pytest.raises(TypeError, match="breakout_lookback"):
        VolatilityExpansionBreakoutStrategy(breakout_lookback=True)


def test_rejects_short_period_below_one() -> None:
    with pytest.raises(ValueError, match="short_period"):
        VolatilityExpansionBreakoutStrategy(short_period=0)


def test_rejects_short_period_not_less_than_long_period() -> None:
    with pytest.raises(ValueError, match="short_period"):
        VolatilityExpansionBreakoutStrategy(short_period=50, long_period=50)


def test_rejects_breakout_lookback_below_one() -> None:
    with pytest.raises(ValueError, match="breakout_lookback"):
        VolatilityExpansionBreakoutStrategy(breakout_lookback=0)


def test_rejects_float_expansion_threshold() -> None:
    with pytest.raises(TypeError, match="expansion_threshold"):
        VolatilityExpansionBreakoutStrategy(expansion_threshold=1.5)  # type: ignore[arg-type]


def test_rejects_non_decimal_expansion_threshold() -> None:
    with pytest.raises(TypeError, match="expansion_threshold"):
        VolatilityExpansionBreakoutStrategy(expansion_threshold="1.5")  # type: ignore[arg-type]


def test_rejects_expansion_threshold_at_one() -> None:
    with pytest.raises(ValueError, match="expansion_threshold"):
        VolatilityExpansionBreakoutStrategy(expansion_threshold=Decimal("1"))


def test_rejects_expansion_threshold_below_one() -> None:
    with pytest.raises(ValueError, match="expansion_threshold"):
        VolatilityExpansionBreakoutStrategy(expansion_threshold=Decimal("0.5"))


# --- evaluate() ---------------------------------------------------------


def test_evaluate_returns_none_with_insufficient_data() -> None:
    strategy = _strategy()
    candles = _candles(_VOLATILITY_BARS[:5])  # need max(long_period, lookback) + 1 = 6

    assert strategy.evaluate(candles) is None


def test_evaluate_fires_long_on_breakout_with_expansion() -> None:
    strategy = _strategy()
    candles = _candles(_VOLATILITY_BARS[:7])  # through index 6

    hypothesis = strategy.evaluate(candles)

    assert hypothesis is not None
    assert hypothesis.target_position is TargetPosition.LONG
    assert hypothesis.instrument == EUR_USD
    assert hypothesis.generated_at == _ts(6)
    assert hypothesis.timeframe is Granularity.M1
    assert hypothesis.strategy_key == "volatility_expansion_breakout_v1"
    assert hypothesis.strategy_version == "1"
    assert hypothesis.parameters == params_from_dict(
        {
            "short_period": 2,
            "long_period": 5,
            "breakout_lookback": 3,
            "expansion_threshold": Decimal("1.5"),
        }
    )
    assert "broke above" in hypothesis.rationale


def test_evaluate_holds_when_expanding_without_a_fresh_breakout() -> None:
    strategy = _strategy()
    candles = _candles(_VOLATILITY_BARS[:8])  # through index 7

    assert strategy.evaluate(candles) is None


def test_evaluate_fires_flat_when_expansion_ends_after_long() -> None:
    strategy = _strategy()
    candles = _candles(_VOLATILITY_BARS[:9])  # through index 8

    hypothesis = strategy.evaluate(candles)

    assert hypothesis is not None
    assert hypothesis.target_position is TargetPosition.FLAT
    assert hypothesis.generated_at == _ts(8)
    assert "contracted below" in hypothesis.rationale


def test_evaluate_holds_on_breakout_without_expansion() -> None:
    strategy = _strategy()
    candles = _candles(_VOLATILITY_BARS[:13])  # through index 12

    assert strategy.evaluate(candles) is None


def test_evaluate_fires_short_on_breakdown_with_expansion() -> None:
    strategy = _strategy()
    candles = _candles(_VOLATILITY_BARS[:17])  # through index 16

    hypothesis = strategy.evaluate(candles)

    assert hypothesis is not None
    assert hypothesis.target_position is TargetPosition.SHORT
    assert hypothesis.generated_at == _ts(16)
    assert "broke below" in hypothesis.rationale


def test_evaluate_fires_flat_when_expansion_ends_after_short() -> None:
    strategy = _strategy()
    candles = _candles(_VOLATILITY_BARS[:18])  # through index 17

    hypothesis = strategy.evaluate(candles)

    assert hypothesis is not None
    assert hypothesis.target_position is TargetPosition.FLAT
    assert hypothesis.generated_at == _ts(17)
