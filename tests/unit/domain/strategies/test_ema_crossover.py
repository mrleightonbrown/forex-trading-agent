"""FX-14: EMA crossover strategy tests.

The reference-EMA test cross-checks the arithmetic itself against a
second, independently written implementation of the same SMA-seeded EMA
algorithm — not just crossover/no-crossover behavior. Same discipline as
ADX's (FX-12) reference-value test.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.strategies.ema_crossover import EmaCrossoverStrategy, _sma_seeded_ema
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trade_hypothesis import params_from_dict
from forex_agent.domain.trade_side import TradeSide

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")

# Engineered so fast=2/slow=3 EMA produces exactly one clean bullish cross
# (index 4) and one clean bearish cross (index 7) — see the derivation
# script used to produce it.
_CROSSOVER_PRICES = [100, 100, 100, 100, 110, 120, 130, 100, 90, 80]


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


# --- reference-value cross-check -------------------------------------------


def test_ema_matches_independent_reference_calculation() -> None:
    closes = [Decimal(p) for p in [100, 102, 101, 105, 107, 106, 110, 112, 111, 115]]

    values = _sma_seeded_ema(closes, period=3)

    # Cross-checked against a second, independently written
    # implementation of the same algorithm.
    expected = [
        "101", "103.0", "105.00", "105.500", "107.7500",
        "109.87500", "110.437500", "112.7187500",
    ]  # fmt: skip
    assert [str(v) for v in values] == expected


# --- constructor validation -------------------------------------------------


def test_default_periods() -> None:
    strategy = EmaCrossoverStrategy()

    assert strategy.fast_period == 20
    assert strategy.slow_period == 50
    assert strategy.strategy_version == "1"


def test_strategy_key_is_a_class_constant() -> None:
    assert EmaCrossoverStrategy.strategy_key == "ema_crossover_v1"


def test_rejects_non_int_fast_period() -> None:
    with pytest.raises(TypeError, match="fast_period"):
        EmaCrossoverStrategy(fast_period=3.5)  # type: ignore[arg-type]


def test_rejects_bool_fast_period() -> None:
    with pytest.raises(TypeError, match="fast_period"):
        EmaCrossoverStrategy(fast_period=True)


def test_rejects_non_int_slow_period() -> None:
    with pytest.raises(TypeError, match="slow_period"):
        EmaCrossoverStrategy(slow_period="50")  # type: ignore[arg-type]


def test_rejects_bool_slow_period() -> None:
    with pytest.raises(TypeError, match="slow_period"):
        EmaCrossoverStrategy(fast_period=1, slow_period=False)


def test_rejects_fast_period_below_one() -> None:
    with pytest.raises(ValueError, match="fast_period"):
        EmaCrossoverStrategy(fast_period=0, slow_period=5)


def test_rejects_fast_period_equal_to_slow_period() -> None:
    with pytest.raises(ValueError, match="fast_period"):
        EmaCrossoverStrategy(fast_period=10, slow_period=10)


def test_rejects_fast_period_greater_than_slow_period() -> None:
    with pytest.raises(ValueError, match="fast_period"):
        EmaCrossoverStrategy(fast_period=50, slow_period=20)


# --- evaluate() ---------------------------------------------------------


def test_evaluate_returns_none_with_insufficient_data() -> None:
    strategy = EmaCrossoverStrategy(fast_period=2, slow_period=3)
    candles = _candles(_CROSSOVER_PRICES[:3])  # need slow_period + 1 = 4

    assert strategy.evaluate(candles) is None


def test_evaluate_returns_none_when_no_crossover() -> None:
    strategy = EmaCrossoverStrategy(fast_period=2, slow_period=3)
    candles = _candles(_CROSSOVER_PRICES[:4])  # diff == 0.0, not a cross

    assert strategy.evaluate(candles) is None


def test_evaluate_fires_long_on_bullish_cross() -> None:
    strategy = EmaCrossoverStrategy(fast_period=2, slow_period=3)
    candles = _candles(_CROSSOVER_PRICES[:5])  # through index 4

    hypothesis = strategy.evaluate(candles)

    assert hypothesis is not None
    assert hypothesis.side is TradeSide.LONG
    assert hypothesis.instrument == EUR_USD
    assert hypothesis.generated_at == _ts(4)
    assert hypothesis.timeframe is Granularity.M1
    assert hypothesis.strategy_key == "ema_crossover_v1"
    assert hypothesis.strategy_version == "1"
    assert hypothesis.parameters == params_from_dict({"fast_period": 2, "slow_period": 3})
    assert "above" in hypothesis.rationale


def test_evaluate_fires_short_on_bearish_cross() -> None:
    strategy = EmaCrossoverStrategy(fast_period=2, slow_period=3)
    candles = _candles(_CROSSOVER_PRICES[:8])  # through index 7

    hypothesis = strategy.evaluate(candles)

    assert hypothesis is not None
    assert hypothesis.side is TradeSide.SHORT
    assert hypothesis.generated_at == _ts(7)
    assert "below" in hypothesis.rationale


def test_evaluate_returns_none_the_bar_after_a_cross() -> None:
    strategy = EmaCrossoverStrategy(fast_period=2, slow_period=3)
    candles = _candles(_CROSSOVER_PRICES[:6])  # one bar past the bullish cross

    assert strategy.evaluate(candles) is None
