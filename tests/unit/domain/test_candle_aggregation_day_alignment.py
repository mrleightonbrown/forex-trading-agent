"""FX-24: day-aligned aggregation (H2/H3/H4/H6/H8/H12/D) tests.

The EDT boundary times used below (09:00/13:00/17:00 UTC on 2026-09-11,
21:00 UTC as the day-anchor after the weekend gap) were confirmed against
a LIVE fetch of OANDA's actual practice-API H4/D candles before writing
this test — not assumed. See docs/DECISIONS.md's FX-24 entry for the
raw fetch. The spring-forward/fall-back cases were independently derived
with a scratch `zoneinfo` script (also recorded there) before being
encoded here; real OANDA data never actually exercises the odd-duration-
bucket path (the US DST transition instant falls inside forex's weekend
closure — also confirmed against a live fetch spanning the real
2026-03-08 transition), so those two tests use synthetic continuous data
to prove the underlying wall-clock arithmetic is correct regardless.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from forex_agent.domain.candle import Candle
from forex_agent.domain.candle_aggregation import aggregate_candles
from forex_agent.domain.candle_source import CandleSource
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.timestamps import UtcTimestamp

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")


def _h1_candle(instant: datetime, price: str = "1.1000") -> Candle:
    p = Decimal(price)
    flat = Ohlc(open=p, high=p, low=p, close=p)
    return Candle(
        instrument=EUR_USD,
        granularity=Granularity.H1,
        start_time=UtcTimestamp(instant),
        bid=flat,
        ask=flat,
        volume=1,
        is_finalized=True,
    )


def _hourly_range(start: datetime, count: int) -> list[Candle]:
    return [_h1_candle(start + timedelta(hours=i)) for i in range(count)]


def _ts(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> UtcTimestamp:
    return UtcTimestamp(datetime(year, month, day, hour, minute, tzinfo=UTC))


# --- summer (EDT): confirmed against a live OANDA fetch -------------------


def test_h4_buckets_match_live_oanda_edt_boundaries() -> None:
    # 2026-09-11 is EDT (UTC-4): 17:00 EDT = 21:00 UTC. 24 consecutive H1
    # candles from 2026-09-10T21:00Z cover exactly 6 complete H4 buckets.
    candles = _hourly_range(datetime(2026, 9, 10, 21, 0, tzinfo=UTC), 24)

    aggregated = aggregate_candles(candles, Granularity.H4)

    assert [c.start_time for c in aggregated] == [
        _ts(2026, 9, 10, 21),
        _ts(2026, 9, 11, 1),
        _ts(2026, 9, 11, 5),
        _ts(2026, 9, 11, 9),  # confirmed against a live OANDA H4 fetch
        _ts(2026, 9, 11, 13),  # confirmed against a live OANDA H4 fetch
        _ts(2026, 9, 11, 17),  # confirmed against a live OANDA H4 fetch
    ]
    assert all(c.granularity is Granularity.H4 for c in aggregated)
    assert all(c.source is CandleSource.AGGREGATED for c in aggregated)


def test_h4_bucket_is_dropped_if_epoch_floor_boundary_used_instead() -> None:
    # Sanity check that this is a REAL behavior change, not a no-op: the
    # OLD epoch-UTC-floored scheme would have bucketed this exact data at
    # 20:00/00:00/04:00/08:00/... UTC, not 21:00/01:00/05:00/09:00/....
    candles = _hourly_range(datetime(2026, 9, 10, 21, 0, tzinfo=UTC), 24)

    aggregated = aggregate_candles(candles, Granularity.H4)

    assert _ts(2026, 9, 10, 20) not in [c.start_time for c in aggregated]
    assert _ts(2026, 9, 11, 9) in [c.start_time for c in aggregated]


# --- winter (EST) ----------------------------------------------------------


def test_h4_buckets_use_est_anchor_in_january() -> None:
    # 2026-01-15 is EST (UTC-5): 17:00 EST = 22:00 UTC.
    candles = _hourly_range(datetime(2026, 1, 14, 22, 0, tzinfo=UTC), 24)

    aggregated = aggregate_candles(candles, Granularity.H4)

    assert [c.start_time for c in aggregated] == [
        _ts(2026, 1, 14, 22),
        _ts(2026, 1, 15, 2),
        _ts(2026, 1, 15, 6),
        _ts(2026, 1, 15, 10),
        _ts(2026, 1, 15, 14),
        _ts(2026, 1, 15, 18),
    ]


# --- D granularity -----------------------------------------------------


def test_daily_bucket_anchors_to_ny_close() -> None:
    # One full EDT trading day (17:00 EDT -> 17:00 EDT, i.e. 21:00 UTC ->
    # 21:00 UTC), fed as H4 source candles this time (6 per day).
    starts = [
        _ts(2026, 9, 10, 21),
        _ts(2026, 9, 11, 1),
        _ts(2026, 9, 11, 5),
        _ts(2026, 9, 11, 9),
        _ts(2026, 9, 11, 13),
        _ts(2026, 9, 11, 17),
    ]
    flat = Ohlc(open=Decimal("1.1"), high=Decimal("1.1"), low=Decimal("1.1"), close=Decimal("1.1"))
    candles = [
        Candle(
            instrument=EUR_USD,
            granularity=Granularity.H4,
            start_time=start,
            bid=flat,
            ask=flat,
            volume=1,
            is_finalized=True,
        )
        for start in starts
    ]

    aggregated = aggregate_candles(candles, Granularity.D)

    assert len(aggregated) == 1
    assert aggregated[0].start_time == _ts(2026, 9, 10, 21)  # 17:00 EDT
    assert aggregated[0].granularity is Granularity.D


# --- H1 and finer are unaffected (regression) ------------------------------


def test_h1_target_still_uses_epoch_floor_not_ny_alignment() -> None:
    # M15 -> H1: must remain simple epoch-UTC-floored, unaffected by FX-24.
    # Starts exactly on the hour so all 4 M15 candles land in one H1 bucket.
    m15_start = datetime(2026, 9, 11, 10, 0, tzinfo=UTC)
    candles = [
        Candle(
            instrument=EUR_USD,
            granularity=Granularity.M15,
            start_time=UtcTimestamp(m15_start + timedelta(minutes=15 * i)),
            bid=Ohlc(
                open=Decimal("1.1"), high=Decimal("1.1"), low=Decimal("1.1"), close=Decimal("1.1")
            ),
            ask=Ohlc(
                open=Decimal("1.1"), high=Decimal("1.1"), low=Decimal("1.1"), close=Decimal("1.1")
            ),
            volume=1,
            is_finalized=True,
        )
        for i in range(4)
    ]

    aggregated = aggregate_candles(candles, Granularity.H1)

    assert len(aggregated) == 1
    assert aggregated[0].start_time == UtcTimestamp(m15_start)  # plain epoch-hour floor


# --- DST transitions: synthetic continuous data -----------------------


def test_spring_forward_bucket_is_short_but_still_complete() -> None:
    # NY trading day 2026-03-07T22:00Z -> 2026-03-08T21:00Z is only 23 REAL
    # hours (spring-forward at 2am EST->3am EDT on 2026-03-08). Independently
    # derived via a scratch zoneinfo script: the 06:00-09:00Z bucket that
    # day spans only 3 real hours, every other bucket a clean 4.
    candles = _hourly_range(datetime(2026, 3, 7, 22, 0, tzinfo=UTC), 23)

    aggregated = aggregate_candles(candles, Granularity.H4)

    starts = [c.start_time for c in aggregated]
    assert starts == [
        _ts(2026, 3, 7, 22),
        _ts(2026, 3, 8, 2),
        _ts(2026, 3, 8, 6),  # the short (3-real-hour) bucket
        _ts(2026, 3, 8, 9),
        _ts(2026, 3, 8, 13),
        _ts(2026, 3, 8, 17),
    ]
    # The short bucket is judged complete with only 3 source candles (it's
    # present in `starts` above), not dropped for being "short" of a naive
    # fixed count of 4. Confirm the reverse too: removing just one of the
    # short bucket's own 3 candles (07:00Z, one of 06:00/07:00/08:00) drops
    # ONLY that bucket -- proving the expected count is genuinely 3 for it,
    # not silently satisfied by fewer.
    missing_one = [c for c in candles if c.start_time != _ts(2026, 3, 8, 7)]
    aggregated_short = aggregate_candles(missing_one, Granularity.H4)
    remaining_starts = [c.start_time for c in aggregated_short]
    assert _ts(2026, 3, 8, 6) not in remaining_starts
    assert _ts(2026, 3, 8, 2) in remaining_starts  # every other bucket unaffected
    assert _ts(2026, 3, 8, 9) in remaining_starts


def test_fall_back_bucket_is_long_but_still_requires_all_five_members() -> None:
    # NY trading day 2026-10-31T21:00Z -> 2026-11-01T22:00Z is 25 REAL hours
    # (fall-back at 2am EDT->1am EST on 2026-11-01). The 05:00-10:00Z
    # bucket that day spans 5 real hours.
    candles = _hourly_range(datetime(2026, 10, 31, 21, 0, tzinfo=UTC), 25)

    aggregated = aggregate_candles(candles, Granularity.H4)

    starts = [c.start_time for c in aggregated]
    assert starts == [
        _ts(2026, 10, 31, 21),
        _ts(2026, 11, 1, 1),
        _ts(2026, 11, 1, 5),  # the long (5-real-hour) bucket
        _ts(2026, 11, 1, 10),
        _ts(2026, 11, 1, 14),
        _ts(2026, 11, 1, 18),
    ]

    # Only 4 of the long bucket's own 5 candles (05:00-09:00Z) -> that
    # bucket is dropped, not emitted as a false "complete" 4-candle
    # bucket; every other bucket that day is unaffected.
    missing_one = [c for c in candles if c.start_time != _ts(2026, 11, 1, 7)]
    aggregated_short = aggregate_candles(missing_one, Granularity.H4)
    remaining_starts = [c.start_time for c in aggregated_short]
    assert _ts(2026, 11, 1, 5) not in remaining_starts
    assert _ts(2026, 11, 1, 1) in remaining_starts
    assert _ts(2026, 11, 1, 10) in remaining_starts
