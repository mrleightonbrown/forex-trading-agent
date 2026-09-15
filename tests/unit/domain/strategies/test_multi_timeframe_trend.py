"""FX-25: multi-timeframe trend confirmation strategy tests.

The engineered series below (h1_fast_period=2, h1_slow_period=3,
h4_fast_period=2, h4_slow_period=3) is hand-derived (independently, via a
separate scratch calculation, not by running the implementation):

H1 closes: 16 flat lead-in hours (100), then
  [100,100,100,110,120,130,100,90,80,90,100,110,120,130,140,150,100,90,80]
  starting at hour 16 (i.e. H1[16]=100 ... H1[34]=80).
H4 closes (one bar per 4 H1 hours, starting hour 0):
  [100,102,104,106,108,110,105,95,85,75,70,65]

  H1 hour 19: EMA crosses toward LONG. 4 H4 bars visible (hours 0-16),
    bias BULLISH -> confirmed LONG.
  H1 hour 22: EMA crosses toward SHORT. 5 H4 bars visible, bias still
    BULLISH -> NOT confirmed -> FLAT.
  H1 hour 26: EMA crosses toward LONG again. 6 H4 bars visible, bias
    still BULLISH -> confirmed LONG.
  H1 hour 32: EMA crosses toward SHORT. 8 H4 bars visible (hours 0-28),
    bias has flipped BEARISH -> confirmed SHORT.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.strategies.multi_timeframe_trend import MultiTimeframeTrendStrategy
from forex_agent.domain.target_position import TargetPosition
from forex_agent.domain.timestamps import UtcTimestamp

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")
GBP_USD = Instrument(base_currency="GBP", quote_currency="USD")

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


def _flat_candle(
    start: UtcTimestamp,
    granularity: Granularity,
    price: int,
    instrument: Instrument = EUR_USD,
    is_finalized: bool = True,
) -> Candle:
    p = Decimal(price)
    flat = Ohlc(open=p, high=p, low=p, close=p)
    return Candle(
        instrument=instrument,
        granularity=granularity,
        start_time=start,
        bid=flat,
        ask=flat,
        volume=1,
        is_finalized=is_finalized,
    )


def _h1_candles(through_hour: int) -> list[Candle]:
    return [_flat_candle(_h1_ts(h), Granularity.H1, _H1_CLOSES[h]) for h in range(through_hour + 1)]


def _h4_candles(count: int) -> list[Candle]:
    return [
        _flat_candle(_h1_ts(4 * k), Granularity.H4, _H4_CLOSES[k])
        for k in range(min(count, len(_H4_CLOSES)))
    ]


def _strategy(h4_count: int = 12) -> MultiTimeframeTrendStrategy:
    return MultiTimeframeTrendStrategy(
        h4_candles=_h4_candles(h4_count),
        h1_fast_period=2,
        h1_slow_period=3,
        h4_fast_period=2,
        h4_slow_period=3,
    )


# --- constructor validation -------------------------------------------------


def test_default_parameters() -> None:
    strategy = MultiTimeframeTrendStrategy(h4_candles=[])

    assert strategy.h1_fast_period == 20
    assert strategy.h1_slow_period == 50
    assert strategy.h4_fast_period == 20
    assert strategy.h4_slow_period == 50
    assert strategy.strategy_version == "1"


def test_strategy_key_is_a_class_constant() -> None:
    assert MultiTimeframeTrendStrategy.strategy_key == "multi_timeframe_trend_v1"


def test_rejects_h4_candles_with_wrong_granularity() -> None:
    wrong = [_flat_candle(_h1_ts(0), Granularity.H1, 100)]

    with pytest.raises(ValueError, match="H4"):
        MultiTimeframeTrendStrategy(h4_candles=wrong)


def test_rejects_h1_fast_period_not_less_than_h1_slow_period() -> None:
    with pytest.raises(ValueError, match="h1_fast_period"):
        MultiTimeframeTrendStrategy(h4_candles=[], h1_fast_period=50, h1_slow_period=50)


def test_rejects_h4_fast_period_not_less_than_h4_slow_period() -> None:
    with pytest.raises(ValueError, match="h4_fast_period"):
        MultiTimeframeTrendStrategy(h4_candles=[], h4_fast_period=50, h4_slow_period=50)


def test_rejects_bool_h1_fast_period() -> None:
    with pytest.raises(TypeError, match="h1_fast_period"):
        MultiTimeframeTrendStrategy(h4_candles=[], h1_fast_period=True)


def test_rejects_period_below_one() -> None:
    with pytest.raises(ValueError, match="h1_fast_period"):
        MultiTimeframeTrendStrategy(h4_candles=[], h1_fast_period=0, h1_slow_period=1)


# --- evaluate() ---------------------------------------------------------


def test_evaluate_fires_long_confirmed_by_bullish_h4() -> None:
    strategy = _strategy()
    candles = _h1_candles(19)

    hypothesis = strategy.evaluate(candles)

    assert hypothesis is not None
    assert hypothesis.target_position is TargetPosition.LONG
    assert hypothesis.instrument == EUR_USD
    assert hypothesis.generated_at == _h1_ts(19)
    assert hypothesis.strategy_key == "multi_timeframe_trend_v1"
    assert "confirmed by H4" in hypothesis.rationale


def test_evaluate_fires_flat_when_h1_signal_not_confirmed_by_h4() -> None:
    strategy = _strategy()
    candles = _h1_candles(22)

    hypothesis = strategy.evaluate(candles)

    assert hypothesis is not None
    assert hypothesis.target_position is TargetPosition.FLAT
    assert hypothesis.generated_at == _h1_ts(22)
    assert "NOT confirmed" in hypothesis.rationale


def test_evaluate_fires_long_again_while_h4_still_bullish() -> None:
    strategy = _strategy()
    candles = _h1_candles(26)

    hypothesis = strategy.evaluate(candles)

    assert hypothesis is not None
    assert hypothesis.target_position is TargetPosition.LONG
    assert hypothesis.generated_at == _h1_ts(26)


def test_evaluate_fires_short_confirmed_once_h4_turns_bearish() -> None:
    strategy = _strategy()
    candles = _h1_candles(32)

    hypothesis = strategy.evaluate(candles)

    assert hypothesis is not None
    assert hypothesis.target_position is TargetPosition.SHORT
    assert hypothesis.generated_at == _h1_ts(32)
    assert "confirmed by H4" in hypothesis.rationale


def test_evaluate_returns_none_with_no_crossover() -> None:
    strategy = _strategy()
    # Hour 20: no crossover event (still riding the same LONG cross).
    candles = _h1_candles(20)

    assert strategy.evaluate(candles) is None


def test_evaluate_returns_none_with_insufficient_h1_history() -> None:
    strategy = _strategy()
    candles = _h1_candles(2)  # h1_slow_period=3 needs 4 candles

    assert strategy.evaluate(candles) is None


def test_h4_with_insufficient_history_is_treated_as_unconfirmed() -> None:
    # Same H1 series, but h4_candles is empty -- the hour-19 LONG signal
    # must NOT be confirmed just because there's nothing to disagree.
    strategy = MultiTimeframeTrendStrategy(
        h4_candles=[], h1_fast_period=2, h1_slow_period=3, h4_fast_period=2, h4_slow_period=3
    )
    candles = _h1_candles(19)

    hypothesis = strategy.evaluate(candles)

    assert hypothesis is not None
    assert hypothesis.target_position is TargetPosition.FLAT


def test_h4_candles_not_yet_closed_are_not_visible() -> None:
    """The specific look-ahead this strategy must avoid: an H4 bar whose
    close is at or after the current H1 bar's start must not affect the
    decision. Confirmed by mutating ONLY that not-yet-visible H4 bar's
    close (the 5th bar, hours 16-20, not yet closed as of H1 hour 19) and
    checking the hour-19 decision is unchanged."""
    baseline = _strategy()
    candles = _h1_candles(19)
    baseline_result = baseline.evaluate(candles)
    assert baseline_result is not None
    assert baseline_result.target_position is TargetPosition.LONG

    mutated_h4 = _h4_candles(12)
    # Bar index 4 covers hours 16-20 -- not yet closed as of H1 hour 19.
    mutated_h4[4] = _flat_candle(_h1_ts(16), Granularity.H4, 5)  # wildly bearish if visible
    mutated_strategy = MultiTimeframeTrendStrategy(
        h4_candles=mutated_h4,
        h1_fast_period=2,
        h1_slow_period=3,
        h4_fast_period=2,
        h4_slow_period=3,
    )

    result = mutated_strategy.evaluate(candles)

    assert result is not None
    assert result.target_position is TargetPosition.LONG  # unaffected


def test_neutral_h4_bias_is_treated_as_unconfirmed() -> None:
    # A perfectly flat H4 series makes fast EMA == slow EMA exactly
    # (NEUTRAL) -- must be treated the same as a disagreement, not
    # confirmed just because nothing contradicts it.
    flat_h4 = [_flat_candle(_h1_ts(4 * k), Granularity.H4, 100) for k in range(6)]
    strategy = MultiTimeframeTrendStrategy(
        h4_candles=flat_h4, h1_fast_period=2, h1_slow_period=3, h4_fast_period=2, h4_slow_period=3
    )
    candles = _h1_candles(19)

    hypothesis = strategy.evaluate(candles)

    assert hypothesis is not None
    assert hypothesis.target_position is TargetPosition.FLAT


def test_rejects_h1_instrument_mismatch_with_h4() -> None:
    strategy = MultiTimeframeTrendStrategy(
        h4_candles=_h4_candles(4), h1_fast_period=2, h1_slow_period=3
    )
    mismatched = [
        _flat_candle(_h1_ts(h), Granularity.H1, 100, instrument=GBP_USD) for h in range(4)
    ]

    with pytest.raises(ValueError, match="instrument"):
        strategy.evaluate(mismatched)
