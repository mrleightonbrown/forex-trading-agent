from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.domain.candle import Candle
from forex_agent.domain.candle_aggregation import aggregate_candles
from forex_agent.domain.candle_source import CandleSource
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.timestamps import UtcTimestamp

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")
GBP_USD = Instrument(base_currency="GBP", quote_currency="USD")


def _m1(
    minute: int, o: str, hi: str, lo: str, c: str, volume: int = 10, finalized: bool = True
) -> Candle:
    return Candle(
        instrument=EUR_USD,
        granularity=Granularity.M1,
        start_time=UtcTimestamp(datetime(2026, 1, 1, 0, minute, 0, tzinfo=UTC)),
        bid=Ohlc(open=Decimal(o), high=Decimal(hi), low=Decimal(lo), close=Decimal(c)),
        ask=Ohlc(
            open=Decimal(o) + Decimal("0.0002"),
            high=Decimal(hi) + Decimal("0.0002"),
            low=Decimal(lo) + Decimal("0.0002"),
            close=Decimal(c) + Decimal("0.0002"),
        ),
        volume=volume,
        is_finalized=finalized,
    )


def test_empty_input_returns_empty_output() -> None:
    assert aggregate_candles([], Granularity.M5) == []


def test_duplicate_plus_missing_member_is_not_falsely_complete() -> None:
    """FX-25H: the original FX-7 edge case a member-COUNT check can't
    catch -- minute 2 is duplicated and minute 3 is missing, so there are
    still exactly 5 records for a 5-minute bucket (a count check would
    accept it), but they are the WRONG 5. Must be dropped, not silently
    aggregated as if genuinely complete.
    """
    candles = [
        _m1(0, "1.1000", "1.1010", "1.0995", "1.1005"),
        _m1(1, "1.1005", "1.1020", "1.1000", "1.1015"),
        _m1(2, "1.1015", "1.1018", "1.0990", "1.1000"),
        _m1(2, "1.1015", "1.1018", "1.0990", "1.1000"),  # duplicate, not minute 3
        _m1(4, "1.0995", "1.1002", "1.0980", "1.0999"),
    ]

    assert aggregate_candles(candles, Granularity.M5) == []


def test_aggregates_one_complete_bucket() -> None:
    candles = [
        _m1(0, "1.1000", "1.1010", "1.0995", "1.1005", volume=10),
        _m1(1, "1.1005", "1.1020", "1.1000", "1.1015", volume=20),
        _m1(2, "1.1015", "1.1018", "1.0990", "1.1000", volume=5),
        _m1(3, "1.1000", "1.1005", "1.0985", "1.0995", volume=7),
        _m1(4, "1.0995", "1.1002", "1.0980", "1.0999", volume=3),
    ]

    aggregated = aggregate_candles(candles, Granularity.M5)

    assert len(aggregated) == 1
    result = aggregated[0]
    assert result.start_time == UtcTimestamp(datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC))
    assert result.bid.open == Decimal("1.1000")  # first candle's open
    assert result.bid.close == Decimal("1.0999")  # last candle's close
    assert result.bid.high == Decimal("1.1020")  # max of all highs
    assert result.bid.low == Decimal("1.0980")  # min of all lows
    assert result.volume == 45  # sum
    assert result.is_finalized is True
    assert result.granularity is Granularity.M5


def test_incomplete_trailing_bucket_is_dropped() -> None:
    # Only 3 of the 5 M1 candles needed for one M5 bucket.
    candles = [
        _m1(0, "1.1000", "1.1010", "1.0995", "1.1005"),
        _m1(1, "1.1005", "1.1020", "1.1000", "1.1015"),
        _m1(2, "1.1015", "1.1018", "1.0990", "1.1000"),
    ]

    assert aggregate_candles(candles, Granularity.M5) == []


def test_non_finalized_member_makes_aggregate_non_finalized() -> None:
    candles = [
        _m1(0, "1.1000", "1.1010", "1.0995", "1.1005", finalized=True),
        _m1(1, "1.1005", "1.1020", "1.1000", "1.1015", finalized=True),
        _m1(2, "1.1015", "1.1018", "1.0990", "1.1000", finalized=True),
        _m1(3, "1.1000", "1.1005", "1.0985", "1.0995", finalized=True),
        _m1(4, "1.0995", "1.1002", "1.0980", "1.0999", finalized=False),
    ]

    aggregated = aggregate_candles(candles, Granularity.M5)

    assert aggregated[0].is_finalized is False


def test_two_consecutive_buckets() -> None:
    candles = [_m1(m, "1.10", "1.11", "1.09", "1.10") for m in range(10)]

    aggregated = aggregate_candles(candles, Granularity.M5)

    assert len(aggregated) == 2
    assert aggregated[0].start_time == UtcTimestamp(datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC))
    assert aggregated[1].start_time == UtcTimestamp(datetime(2026, 1, 1, 0, 5, 0, tzinfo=UTC))


def _flat_candle(
    instrument: Instrument, granularity: Granularity, minute: int, price: str
) -> Candle:
    flat = Ohlc(open=Decimal(price), high=Decimal(price), low=Decimal(price), close=Decimal(price))
    return Candle(
        instrument=instrument,
        granularity=granularity,
        start_time=UtcTimestamp(datetime(2026, 1, 1, 0, minute, 0, tzinfo=UTC)),
        bid=flat,
        ask=flat,
        volume=1,
        is_finalized=True,
    )


def test_rejects_mixed_instruments() -> None:
    other = _flat_candle(GBP_USD, Granularity.M1, 1, "1.3")
    candles = [_m1(0, "1.1", "1.1", "1.1", "1.1"), other]

    with pytest.raises(ValueError, match="instrument"):
        aggregate_candles(candles, Granularity.M5)


def test_rejects_mixed_source_provenance() -> None:
    # FX-24: aggregating a mix of NATIVE and AGGREGATED source candles
    # would silently blend two potentially differently-aligned datasets.
    native = _m1(0, "1.1", "1.1", "1.1", "1.1")
    aggregated = Candle(
        instrument=EUR_USD,
        granularity=Granularity.M1,
        start_time=UtcTimestamp(datetime(2026, 1, 1, 0, 1, 0, tzinfo=UTC)),
        bid=Ohlc(
            open=Decimal("1.1"), high=Decimal("1.1"), low=Decimal("1.1"), close=Decimal("1.1")
        ),
        ask=Ohlc(
            open=Decimal("1.1"), high=Decimal("1.1"), low=Decimal("1.1"), close=Decimal("1.1")
        ),
        volume=1,
        is_finalized=True,
        source=CandleSource.AGGREGATED,
    )
    candles = [native, aggregated]

    with pytest.raises(ValueError, match="source"):
        aggregate_candles(candles, Granularity.M5)


def test_rejects_mixed_source_granularity() -> None:
    other = _flat_candle(EUR_USD, Granularity.M5, 0, "1.1")
    candles = [_m1(0, "1.1", "1.1", "1.1", "1.1"), other]

    with pytest.raises(ValueError, match="granularity"):
        aggregate_candles(candles, Granularity.M15)


def test_rejects_non_multiple_target_duration() -> None:
    # M4 (4 min) source, M10 (10 min) target: 10 is not a whole multiple of 4.
    m4_candle = _flat_candle(EUR_USD, Granularity.M4, 0, "1.1")

    with pytest.raises(ValueError, match="whole multiple"):
        aggregate_candles([m4_candle], Granularity.M10)


def test_rejects_target_smaller_than_source() -> None:
    m5_candle = _flat_candle(EUR_USD, Granularity.M5, 0, "1.1")

    with pytest.raises(ValueError, match="whole multiple"):
        aggregate_candles([m5_candle], Granularity.M1)
