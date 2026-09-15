"""FX-21 (look-ahead fixed in FX-21H): regime segmentation tests.

Reuses FX-12's own already-verified fixtures (steadily increasing prices
-> TRENDING, perfectly flat prices -> RANGING) rather than re-deriving
ADX arithmetic — this module's job is bucketing, not classification.

`test_entry_candles_own_ohlc_does_not_affect_classification` is the
specific look-ahead regression FX-21H added: it proves the entry
candle's own high/low/close cannot influence its trade's regime label,
mirroring FX-11H's own look-ahead regression precedent.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.money import Money
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.regime_segmentation import segment_trades_by_regime
from forex_agent.domain.simulated_trade import SimulatedTrade
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trade_side import TradeSide

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")
GBP_USD = Instrument(base_currency="GBP", quote_currency="USD")


def _ts(minute: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, 0, minute, 0, tzinfo=UTC))


def _flat_candle(minute: int, price: str, instrument: Instrument = EUR_USD) -> Candle:
    p = Decimal(price)
    flat = Ohlc(open=p, high=p, low=p, close=p)
    return Candle(
        instrument=instrument,
        granularity=Granularity.M1,
        start_time=_ts(minute),
        bid=flat,
        ask=flat,
        volume=1,
        is_finalized=True,
    )


def _candles(prices: list[str]) -> list[Candle]:
    return [_flat_candle(i, p) for i, p in enumerate(prices)]


def _trade(entry_minute: int, exit_minute: int, instrument: Instrument = EUR_USD) -> SimulatedTrade:
    return SimulatedTrade(
        instrument=instrument,
        side=TradeSide.LONG,
        entry_price=Decimal("1.1000"),
        entry_time=_ts(entry_minute),
        exit_price=Decimal("1.1010"),
        exit_time=_ts(exit_minute),
        pnl=Money(Decimal("10"), "USD"),
    )


# Same 30-bar fixture as test_regime_detection.py's
# test_strongly_trending_series_classifies_as_trending.
_TRENDING_PRICES = [str(100 + i) for i in range(30)]
# Same 30-bar fixture as test_flat_series_classifies_as_ranging.
_RANGING_PRICES = ["100"] * 30


def test_trending_trade_is_bucketed_as_trending() -> None:
    candles = _candles(_TRENDING_PRICES)
    trade = _trade(29, 29)  # entered on the last candle; classified on candles 0-28

    result = segment_trades_by_regime([trade], candles, period=14)

    assert result.trending == [trade]
    assert result.ranging == []
    assert result.unclassified == []


def test_ranging_trade_is_bucketed_as_ranging() -> None:
    candles = _candles(_RANGING_PRICES)
    trade = _trade(29, 29)

    result = segment_trades_by_regime([trade], candles, period=14)

    assert result.ranging == [trade]
    assert result.trending == []
    assert result.unclassified == []


def test_early_trade_with_insufficient_history_is_unclassified() -> None:
    candles = _candles(_TRENDING_PRICES[:10])  # period=14 needs 2*14=28
    trade = _trade(5, 5)

    result = segment_trades_by_regime([trade], candles, period=14)

    assert result.unclassified == [trade]
    assert result.trending == []
    assert result.ranging == []


def test_multiple_trades_sorted_into_different_buckets() -> None:
    candles = _candles(_TRENDING_PRICES)  # 30 candles, period=14 needs 28
    early_trade = _trade(10, 10)  # history (candles 0-9) length 10 < 28: unclassified
    late_trade = _trade(29, 29)  # history (candles 0-28) length 29 >= 28: trending

    result = segment_trades_by_regime([early_trade, late_trade], candles, period=14)

    assert result.unclassified == [early_trade]
    assert result.trending == [late_trade]
    assert result.ranging == []


def test_empty_trades_returns_empty_buckets() -> None:
    candles = _candles(_TRENDING_PRICES)

    result = segment_trades_by_regime([], candles, period=14)

    assert result == segment_trades_by_regime([], candles, period=14)
    assert result.trending == []
    assert result.ranging == []
    assert result.unclassified == []


def test_period_and_threshold_are_configurable() -> None:
    # Same 8-candle fixture as test_regime_detection.py's
    # test_threshold_is_configurable: reference ADX ~73.29.
    candles = _candles(["100", "102", "101", "105", "107", "106", "110", "112"])
    trade = _trade(7, 7)

    trending = segment_trades_by_regime([trade], candles, period=3, threshold=Decimal("1"))
    assert trending.trending == [trade]

    ranging = segment_trades_by_regime([trade], candles, period=3, threshold=Decimal("99"))
    assert ranging.ranging == [trade]


# --- FX-21H: look-ahead regression ------------------------------------


def test_entry_candles_own_ohlc_does_not_affect_classification() -> None:
    """The specific bug FX-21H fixed: a trade's regime label must not
    depend on its own entry candle's high/low/close, since only that
    candle's open is known at the instant of entry (FX-11H).

    Uses a choppy/oscillating 29-bar prefix (ADX ~3.53, RANGING at any
    reasonable threshold) with a dramatically mutated 30th (entry) bar,
    and a `threshold` chosen so that INCLUDING that mutated entry bar
    would tip ADX from ~3.53 up to ~8.00 -- crossing the threshold to
    TRENDING. The correct result is RANGING: the mutated entry candle
    must be excluded entirely, not merely outvoted. Confirmed against
    `_compute_adx` directly before writing this test (with vs. without
    the entry candle: 3.53 vs. 8.00 for this exact series) -- the old
    `candles[:entry_index + 1]` slicing would have produced TRENDING
    here; the fixed `candles[:entry_index]` slicing must produce
    RANGING.
    """
    choppy_prefix = [str(100 + (2 if i % 2 == 0 else -2)) for i in range(29)]
    mutated_entry_price = "200"  # wildly outside the +-2 oscillation
    candles = [*_candles(choppy_prefix), _flat_candle(29, mutated_entry_price)]
    trade = _trade(29, 29)

    result = segment_trades_by_regime([trade], candles, period=14, threshold=Decimal("6"))

    assert result.ranging == [trade]
    assert result.trending == []
    assert result.unclassified == []


# --- validation ---------------------------------------------------------


def test_rejects_empty_candles() -> None:
    with pytest.raises(ValueError, match="candles"):
        segment_trades_by_regime([], [])


def test_rejects_trade_instrument_mismatch() -> None:
    candles = _candles(_TRENDING_PRICES)
    trade = _trade(29, 29, instrument=GBP_USD)

    with pytest.raises(ValueError, match="instrument"):
        segment_trades_by_regime([trade], candles)


def test_rejects_trade_with_no_matching_candle() -> None:
    candles = _candles(_TRENDING_PRICES)
    trade = _trade(45, 45)  # no candle at minute 45 (only 0-29 exist)

    with pytest.raises(ValueError, match="does not"):
        segment_trades_by_regime([trade], candles)
