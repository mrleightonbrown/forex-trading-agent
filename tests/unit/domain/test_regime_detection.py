"""FX-12: regime detection tests.

The reference-ADX test cross-checks the arithmetic itself against a
second, independently written implementation of the same standard Wilder
ADX algorithm (see the derivation script used to produce the expected
value) — not just the TRENDING/RANGING threshold behavior.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.regime_detection import _compute_adx, classify_regime
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trend_regime import TrendRegime

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")
GBP_USD = Instrument(base_currency="GBP", quote_currency="USD")


def _ts(minute: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, 0, minute, 0, tzinfo=UTC))


def _flat_candle(
    minute: int,
    price: str,
    *,
    instrument: Instrument = EUR_USD,
    granularity: Granularity = Granularity.M1,
    is_finalized: bool = True,
) -> Candle:
    """A candle with open == high == low == close == price on both sides
    (zero spread) — keeps the reference-value math simple: mid == price."""
    p = Decimal(price)
    flat = Ohlc(open=p, high=p, low=p, close=p)
    return Candle(
        instrument=instrument,
        granularity=granularity,
        start_time=_ts(minute),
        bid=flat,
        ask=flat,
        volume=1,
        is_finalized=is_finalized,
    )


def _candles(prices: list[str]) -> list[Candle]:
    return [_flat_candle(i, p) for i, p in enumerate(prices)]


# --- reference-value cross-check ------------------------------------------


def test_adx_matches_independent_reference_calculation() -> None:
    # Cross-checked against a second, independently written
    # implementation of the same algorithm — see the FX-12 completion
    # notes for the derivation. Expected to 6 decimal places; the
    # reference float value is 73.29432870314437.
    candles = _candles(["100", "102", "101", "105", "107", "106", "110", "112"])

    adx = _compute_adx(candles, period=3)

    assert adx.quantize(Decimal("0.000001")) == Decimal("73.294329")


# --- qualitative classification -------------------------------------------


def test_strongly_trending_series_classifies_as_trending() -> None:
    # Steadily increasing highs/lows/closes, no pullbacks: textbook strong
    # uptrend, should produce high ADX.
    prices = [str(100 + i) for i in range(30)]
    candles = _candles(prices)

    assert classify_regime(candles, period=14) is TrendRegime.TRENDING


def test_flat_series_classifies_as_ranging() -> None:
    # Perfectly flat: no directional movement at all, ADX should be ~0.
    prices = ["100"] * 30
    candles = _candles(prices)

    assert classify_regime(candles, period=14) is TrendRegime.RANGING


def test_choppy_oscillating_series_classifies_as_ranging() -> None:
    # Oscillates up/down with no net direction: classic ranging market.
    prices = [str(100 + (2 if i % 2 == 0 else -2)) for i in range(30)]
    candles = _candles(prices)

    assert classify_regime(candles, period=14) is TrendRegime.RANGING


def test_threshold_is_configurable() -> None:
    candles = _candles(["100", "102", "101", "105", "107", "106", "110", "112"])

    # The reference ADX for this series is ~73.29 — a very low threshold
    # must classify it as trending, an impossibly high one as ranging.
    assert classify_regime(candles, period=3, threshold=Decimal("1")) is TrendRegime.TRENDING
    assert classify_regime(candles, period=3, threshold=Decimal("99")) is TrendRegime.RANGING


# --- validation -------------------------------------------------------------


def test_rejects_insufficient_candles() -> None:
    candles = _candles([str(100 + i) for i in range(10)])  # need 2*14=28

    with pytest.raises(ValueError, match="at least 28"):
        classify_regime(candles, period=14)


def test_exactly_minimum_candles_is_accepted() -> None:
    candles = _candles([str(100 + i) for i in range(6)])  # exactly 2*3

    classify_regime(candles, period=3)  # does not raise


def test_rejects_mixed_instruments() -> None:
    candles = _candles([str(100 + i) for i in range(6)])
    candles[3] = _flat_candle(3, "103", instrument=GBP_USD)

    with pytest.raises(ValueError, match="instrument"):
        classify_regime(candles, period=3)


def test_rejects_mixed_granularity() -> None:
    candles = _candles([str(100 + i) for i in range(6)])
    candles[3] = _flat_candle(3, "103", granularity=Granularity.M5)

    with pytest.raises(ValueError, match="granularity"):
        classify_regime(candles, period=3)


def test_rejects_non_finalized_candle() -> None:
    candles = _candles([str(100 + i) for i in range(6)])
    candles[3] = _flat_candle(3, "103", is_finalized=False)

    with pytest.raises(ValueError, match="finalized"):
        classify_regime(candles, period=3)
