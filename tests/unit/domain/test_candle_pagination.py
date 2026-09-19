"""FX-26: candle-range pagination tests."""

from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest

from forex_agent.domain.candle_boundary import candle_start_boundary
from forex_agent.domain.candle_pagination import CandlePage, split_into_pages
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.timestamps import UtcTimestamp


def _ts(instant: datetime) -> UtcTimestamp:
    return UtcTimestamp(instant)


# --- validation -------------------------------------------------------------


def test_rejects_non_int_max_candles_per_page() -> None:
    start = _ts(datetime(2026, 1, 1, tzinfo=UTC))
    end = _ts(datetime(2026, 1, 2, tzinfo=UTC))

    with pytest.raises(TypeError, match="max_candles_per_page"):
        split_into_pages(start, end, Granularity.M1, 5.5)  # type: ignore[arg-type]


def test_rejects_bool_max_candles_per_page() -> None:
    start = _ts(datetime(2026, 1, 1, tzinfo=UTC))
    end = _ts(datetime(2026, 1, 2, tzinfo=UTC))

    with pytest.raises(TypeError, match="max_candles_per_page"):
        split_into_pages(start, end, Granularity.M1, True)


def test_rejects_max_candles_per_page_below_one() -> None:
    start = _ts(datetime(2026, 1, 1, tzinfo=UTC))
    end = _ts(datetime(2026, 1, 2, tzinfo=UTC))

    with pytest.raises(ValueError, match="max_candles_per_page"):
        split_into_pages(start, end, Granularity.M1, 0)


def test_returns_empty_list_when_end_is_not_after_start() -> None:
    same = _ts(datetime(2026, 1, 1, tzinfo=UTC))
    later = _ts(datetime(2026, 1, 2, tzinfo=UTC))

    assert split_into_pages(same, same, Granularity.M1, 100) == []
    assert split_into_pages(later, same, Granularity.M1, 100) == []


# --- basic splitting ---------------------------------------------------------


def test_single_page_when_range_fits() -> None:
    start = _ts(datetime(2026, 1, 1, 0, 0, tzinfo=UTC))
    end = _ts(datetime(2026, 1, 1, 0, 5, tzinfo=UTC))  # 5 M1 candles

    pages = split_into_pages(start, end, Granularity.M1, 10)

    assert pages == [CandlePage(start, end)]


def test_exact_page_boundary_produces_no_trailing_partial_page() -> None:
    # Exactly 10 M1 candles, max_candles_per_page=5 -> exactly 2 full pages.
    start = _ts(datetime(2026, 1, 1, 0, 0, tzinfo=UTC))
    end = _ts(datetime(2026, 1, 1, 0, 10, tzinfo=UTC))

    pages = split_into_pages(start, end, Granularity.M1, 5)

    assert pages == [
        CandlePage(
            _ts(datetime(2026, 1, 1, 0, 0, tzinfo=UTC)), _ts(datetime(2026, 1, 1, 0, 5, tzinfo=UTC))
        ),
        CandlePage(
            _ts(datetime(2026, 1, 1, 0, 5, tzinfo=UTC)),
            _ts(datetime(2026, 1, 1, 0, 10, tzinfo=UTC)),
        ),
    ]


def test_5001_candles_produces_exactly_two_pages() -> None:
    # The exact OANDA cap boundary: 5000 M1 candles is one page; a 5001st
    # candle forces a second, 1-candle page.
    start = _ts(datetime(2026, 1, 1, 0, 0, tzinfo=UTC))
    end = _ts(start.value + timedelta(minutes=5001))

    pages = split_into_pages(start, end, Granularity.M1, 5000)

    assert len(pages) == 2
    assert pages[0].start == start
    assert pages[0].end == _ts(start.value + timedelta(minutes=5000))
    assert pages[1].start == pages[0].end
    assert pages[1].end == end


def test_5000_candles_produces_exactly_one_page() -> None:
    start = _ts(datetime(2026, 1, 1, 0, 0, tzinfo=UTC))
    end = _ts(start.value + timedelta(minutes=5000))

    pages = split_into_pages(start, end, Granularity.M1, 5000)

    assert len(pages) == 1
    assert pages[0] == CandlePage(start, end)


def test_pages_are_contiguous_with_no_gap_or_overlap() -> None:
    start = _ts(datetime(2026, 1, 1, 0, 0, tzinfo=UTC))
    end = _ts(start.value + timedelta(minutes=137))  # not a clean multiple

    pages = split_into_pages(start, end, Granularity.M1, 10)

    assert pages[0].start == start
    assert pages[-1].end == end
    for earlier, later in pairwise(pages):
        assert earlier.end == later.start


def test_snaps_a_non_boundary_start_to_the_candle_boundary_containing_it() -> None:
    # M15 candle boundaries are at :00/:15/:30/:45; start mid-candle.
    mid_candle = _ts(datetime(2026, 1, 1, 0, 7, tzinfo=UTC))
    end = _ts(datetime(2026, 1, 1, 1, 0, tzinfo=UTC))

    pages = split_into_pages(mid_candle, end, Granularity.M15, 100)

    assert pages[0].start == _ts(datetime(2026, 1, 1, 0, 0, tzinfo=UTC))


# --- DST-aware pagination (day-aligned granularities) -----------------------


def test_h4_page_spanning_spring_forward_counts_the_short_bucket_correctly() -> None:
    # Same verified boundaries as FX-25H: 2026-03-07T22:00Z -> 6 H4
    # candles that day, the 3rd one (06:00-09:00Z) DST-shortened to 3
    # real hours. A 2-candle-per-page split must still land exactly on
    # real candle boundaries throughout, including across that bucket.
    start = _ts(datetime(2026, 3, 7, 22, 0, tzinfo=UTC))
    end = _ts(datetime(2026, 3, 8, 21, 0, tzinfo=UTC))  # 6 H4 candles total

    pages = split_into_pages(start, end, Granularity.H4, 2)

    assert [p.start for p in pages] == [
        _ts(datetime(2026, 3, 7, 22, 0, tzinfo=UTC)),
        _ts(datetime(2026, 3, 8, 6, 0, tzinfo=UTC)),
        _ts(datetime(2026, 3, 8, 13, 0, tzinfo=UTC)),
    ]
    assert pages[-1].end == end
    # Every page boundary is a genuine H4 candle boundary -- none land
    # mid-candle because of the DST-shortened 3rd bucket.
    for page in pages:
        assert candle_start_boundary(page.start.value, Granularity.H4) == page.start.value


def test_h4_page_spanning_fall_back_counts_the_long_bucket_correctly() -> None:
    # Same verified boundaries as FX-25H: 2026-10-31T21:00Z -> 6 H4
    # candles that day, the 3rd one (05:00-10:00Z) lengthened to 5 real
    # hours.
    start = _ts(datetime(2026, 10, 31, 21, 0, tzinfo=UTC))
    end = _ts(datetime(2026, 11, 1, 22, 0, tzinfo=UTC))  # 6 H4 candles total

    pages = split_into_pages(start, end, Granularity.H4, 3)

    assert [p.start for p in pages] == [
        _ts(datetime(2026, 10, 31, 21, 0, tzinfo=UTC)),
        _ts(datetime(2026, 11, 1, 10, 0, tzinfo=UTC)),
    ]
    assert pages[-1].end == end
    for page in pages:
        assert candle_start_boundary(page.start.value, Granularity.H4) == page.start.value


# --- determinism regardless of page size ------------------------------------


def test_page_boundaries_never_land_mid_candle_regardless_of_page_size() -> None:
    """The deterministic-final-dataset property: however a range is
    sliced, no page boundary may fall in the middle of a real candle --
    proven across several page sizes, spanning a DST transition, for a
    day-aligned granularity."""
    start = _ts(datetime(2026, 3, 7, 22, 0, tzinfo=UTC))
    end = _ts(datetime(2026, 3, 9, 21, 0, tzinfo=UTC))  # spans the transition day

    for max_candles_per_page in (1, 2, 3, 5, 100):
        pages = split_into_pages(start, end, Granularity.H4, max_candles_per_page)

        assert pages[0].start == start
        assert pages[-1].end == end
        for earlier, later in pairwise(pages):
            assert earlier.end == later.start
        for page in pages:
            assert candle_start_boundary(page.start.value, Granularity.H4) == page.start.value
