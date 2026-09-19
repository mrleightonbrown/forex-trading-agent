from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.domain.candle import Candle
from forex_agent.domain.candle_gaps import find_gaps
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.timestamps import UtcTimestamp

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")
GBP_USD = Instrument(base_currency="GBP", quote_currency="USD")


def _ts(minute: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, 0, minute, 0, tzinfo=UTC))


def _m1(minute: int, instrument: Instrument = EUR_USD) -> Candle:
    flat = Ohlc(open=Decimal("1.1"), high=Decimal("1.1"), low=Decimal("1.1"), close=Decimal("1.1"))
    return Candle(
        instrument=instrument,
        granularity=Granularity.M1,
        start_time=_ts(minute),
        bid=flat,
        ask=flat,
        volume=1,
        is_finalized=True,
    )


def test_no_gaps_when_all_expected_candles_present() -> None:
    candles = [_m1(m) for m in range(5)]

    gaps = find_gaps(candles, Granularity.M1, _ts(0), _ts(5))

    assert gaps == []


def test_finds_gap_in_the_middle() -> None:
    candles = [_m1(0), _m1(1), _m1(3), _m1(4)]  # minute 2 missing

    gaps = find_gaps(candles, Granularity.M1, _ts(0), _ts(5))

    assert gaps == [_ts(2)]


def test_finds_gap_at_start_and_end() -> None:
    candles = [_m1(1), _m1(2), _m1(3)]  # minutes 0 and 4 missing

    gaps = find_gaps(candles, Granularity.M1, _ts(0), _ts(5))

    assert gaps == [_ts(0), _ts(4)]


def test_empty_candles_means_every_slot_is_a_gap() -> None:
    gaps = find_gaps([], Granularity.M1, _ts(0), _ts(3))

    assert gaps == [_ts(0), _ts(1), _ts(2)]


def test_empty_range_has_no_gaps() -> None:
    assert find_gaps([], Granularity.M1, _ts(0), _ts(0)) == []


def test_gaps_are_sorted_regardless_of_candle_order() -> None:
    candles = [_m1(4), _m1(0), _m1(3)]  # minutes 1, 2 missing; input unsorted

    gaps = find_gaps(candles, Granularity.M1, _ts(0), _ts(5))

    assert gaps == [_ts(1), _ts(2)]


def test_rejects_candle_with_mismatched_granularity() -> None:
    flat = Ohlc(open=Decimal("1.1"), high=Decimal("1.1"), low=Decimal("1.1"), close=Decimal("1.1"))
    wrong = Candle(
        instrument=EUR_USD,
        granularity=Granularity.M5,
        start_time=_ts(0),
        bid=flat,
        ask=flat,
        volume=1,
        is_finalized=True,
    )

    with pytest.raises(ValueError, match="granularity"):
        find_gaps([wrong], Granularity.M1, _ts(0), _ts(5))


def test_rejects_mixed_instrument_candles() -> None:
    # FX-11H (AC8): a GBP/USD candle at minute 1 must not be able to fill
    # EUR/USD's expected slot at minute 1 and hide a real gap.
    candles = [_m1(0), _m1(1, instrument=GBP_USD), _m1(2)]

    with pytest.raises(ValueError, match="instrument"):
        find_gaps(candles, Granularity.M1, _ts(0), _ts(3))


# --- FX-26: day-aligned granularities use canonical boundaries -------------


def _h4(instant: datetime, instrument: Instrument = EUR_USD) -> Candle:
    flat = Ohlc(open=Decimal("1.1"), high=Decimal("1.1"), low=Decimal("1.1"), close=Decimal("1.1"))
    return Candle(
        instrument=instrument,
        granularity=Granularity.H4,
        start_time=UtcTimestamp(instant),
        bid=flat,
        ask=flat,
        volume=1,
        is_finalized=True,
    )


def test_no_false_gaps_across_a_spring_forward_h4_transition() -> None:
    """FX-26 regression: the naive epoch-stepping this replaced would
    have generated expected boundaries 4 real hours apart throughout,
    diverging from the real (FX-24-confirmed) canonical H4 boundaries by
    an hour from the DST transition onward -- reporting a false gap (or
    hiding a real one) for every candle after it. All six real boundaries
    for this day, independently confirmed against candle_boundary and
    matching FX-25H's own verified values, are supplied here and must
    show zero gaps.
    """
    real_h4_boundaries = [
        datetime(2026, 3, 7, 22, 0, tzinfo=UTC),
        datetime(2026, 3, 8, 2, 0, tzinfo=UTC),
        datetime(2026, 3, 8, 6, 0, tzinfo=UTC),
        datetime(2026, 3, 8, 9, 0, tzinfo=UTC),  # would be 10:00Z under naive +4h stepping
        datetime(2026, 3, 8, 13, 0, tzinfo=UTC),
        datetime(2026, 3, 8, 17, 0, tzinfo=UTC),
    ]
    candles = [_h4(t) for t in real_h4_boundaries]

    gaps = find_gaps(
        candles,
        Granularity.H4,
        UtcTimestamp(datetime(2026, 3, 7, 22, 0, tzinfo=UTC)),
        UtcTimestamp(datetime(2026, 3, 8, 21, 0, tzinfo=UTC)),
    )

    assert gaps == []


def test_correctly_identifies_a_missing_candle_around_a_dst_transition() -> None:
    # Same six real boundaries as above, but the DST-shortened 09:00Z
    # candle is missing -- must be reported as the gap, not some other
    # (naively-computed, wrong) timestamp.
    real_h4_boundaries = [
        datetime(2026, 3, 7, 22, 0, tzinfo=UTC),
        datetime(2026, 3, 8, 2, 0, tzinfo=UTC),
        datetime(2026, 3, 8, 6, 0, tzinfo=UTC),
        # 09:00Z intentionally missing
        datetime(2026, 3, 8, 13, 0, tzinfo=UTC),
        datetime(2026, 3, 8, 17, 0, tzinfo=UTC),
    ]
    candles = [_h4(t) for t in real_h4_boundaries]

    gaps = find_gaps(
        candles,
        Granularity.H4,
        UtcTimestamp(datetime(2026, 3, 7, 22, 0, tzinfo=UTC)),
        UtcTimestamp(datetime(2026, 3, 8, 21, 0, tzinfo=UTC)),
    )

    assert gaps == [UtcTimestamp(datetime(2026, 3, 8, 9, 0, tzinfo=UTC))]
