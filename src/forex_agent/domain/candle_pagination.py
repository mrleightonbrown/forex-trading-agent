"""FX-26: splits a candle date range into provider-safe pages — pure, no
I/O. A page's candle count has to be computed exactly, the same
discipline FX-25H/FX-25H.1 established for aggregation: a day-aligned
granularity's candle can be 3, 4, or 5 real hours depending on DST, so
"how much real time does N candles span" can't be a fixed multiplication
for those granularities. Non-day-aligned granularities (`H1` and finer)
have no such ambiguity, so a closed-form calculation is used there
instead of walking `candle_end_time` N times — the same exact boundary
either way, just faster for the common case.

Pages are contiguous and non-overlapping by construction:
`pages[i].end == pages[i + 1].start`, always, for any `max_candles_per_page`
— proven, not just intended (see the test suite's determinism check).
"""

from dataclasses import dataclass
from datetime import datetime

from forex_agent.domain.candle_boundary import (
    DAY_ALIGNED_GRANULARITIES,
    candle_end_time,
    candle_start_boundary,
)
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.granularity_duration import fixed_duration
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class CandlePage:
    start: UtcTimestamp
    end: UtcTimestamp


def split_into_pages(
    start: UtcTimestamp,
    end: UtcTimestamp,
    granularity: Granularity,
    max_candles_per_page: int,
) -> list[CandlePage]:
    """Split `[start, end)` into pages of at most `max_candles_per_page`
    candles at `granularity`, anchored to that granularity's own
    canonical boundaries (`candle_boundary.candle_start_boundary`) rather
    than trusting `start` to already be exactly aligned.

    Raises `ValueError` if `max_candles_per_page` isn't a positive `int`.
    Returns `[]` if `end` isn't after `start`.
    """
    if isinstance(max_candles_per_page, bool) or not isinstance(max_candles_per_page, int):
        raise TypeError(
            f"max_candles_per_page must be an int, got {type(max_candles_per_page).__name__}"
        )
    if max_candles_per_page < 1:
        raise ValueError(f"max_candles_per_page must be at least 1, got {max_candles_per_page}")
    if end.value <= start.value:
        return []

    pages = []
    cursor = candle_start_boundary(start.value, granularity)
    while cursor < end.value:
        page_end = _advance(cursor, granularity, max_candles_per_page)
        if page_end > end.value:
            page_end = end.value
        pages.append(CandlePage(UtcTimestamp(cursor), UtcTimestamp(page_end)))
        cursor = page_end

    return pages


def _advance(instant: datetime, granularity: Granularity, count: int) -> datetime:
    """`instant` advanced by exactly `count` candles of `granularity` —
    a closed-form multiplication for non-day-aligned granularities (no
    DST ambiguity to walk through one candle at a time), the exact
    canonical walk for day-aligned ones."""
    if granularity not in DAY_ALIGNED_GRANULARITIES:
        return instant + fixed_duration(granularity) * count

    cursor = instant
    for _ in range(count):
        cursor = candle_end_time(cursor, granularity)
    return cursor
