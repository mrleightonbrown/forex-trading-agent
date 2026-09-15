"""FX-7 (day-aligned bucketing fixed FX-24): pure candle aggregation — no
I/O, no repository access.

Reading source candles back out of storage and persisting aggregates is a
separate concern (a future use case), not built here.

FX-24: OANDA's day-aligned granularities (H2/H3/H4/H6/H8/H12/D — confirmed
live against the practice API, not assumed) anchor to 17:00
`America/New_York`, DST-shifting in UTC terms — NOT epoch-UTC-floored
fixed-duration buckets, which is what this module used for every
granularity until now. `H1` and finer are unaffected: an hour is a fixed
duration with no DST ambiguity (`America/New_York`'s UTC offset is always
a whole number of hours), so epoch-floored hour buckets already agree
with NY-local hour buckets.

A day-aligned bucket that contains a DST transition genuinely spans 3 or
5 real hours, not 4 (or whatever the target duration nominally is) — a
"complete" bucket's expected member count therefore has to be computed
per bucket from its own real elapsed time, not a single fixed constant.
Real forex data never actually exercises this (US DST transitions happen
at 2am local on a Sunday, entirely inside the weekend closure — confirmed
against a live fetch spanning the real March 2026 transition), but the
function doesn't get to assume that; it's a general-purpose aggregator.
"""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from forex_agent.domain.candle import Candle
from forex_agent.domain.candle_source import CandleSource
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.granularity_duration import fixed_duration
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.timestamps import UtcTimestamp

_NY_ZONE = ZoneInfo("America/New_York")
_NY_DAILY_ALIGNMENT_HOUR = 17  # matches OANDA's own default dailyAlignment=17

# Day-aligned per OANDA's own documented granularity semantics: H1 and
# finer are hour-aligned (no DST ambiguity); these are day-aligned to a
# 17:00 America/New_York close instead of epoch-UTC midnight.
_DAY_ALIGNED_GRANULARITIES = frozenset(
    {
        Granularity.H2,
        Granularity.H3,
        Granularity.H4,
        Granularity.H6,
        Granularity.H8,
        Granularity.H12,
        Granularity.D,
    }
)


def aggregate_candles(candles: list[Candle], into: Granularity) -> list[Candle]:
    """Group `candles` (must share one instrument and one source
    granularity) into `into`-duration buckets, and produce one aggregated
    candle per *complete* bucket.

    Buckets for `into` in `H2`/`H3`/`H4`/`H6`/`H8`/`H12`/`D` are anchored
    to 17:00 `America/New_York` (FX-24), matching OANDA's own native
    candles for those granularities — DST-aware via `zoneinfo`, not a
    fixed UTC duration walked from the Unix epoch. Every other target
    granularity keeps the original epoch-UTC-floored fixed-duration
    bucketing (`H1` and finer have no DST ambiguity to account for).

    A trailing (or DST-shortened) bucket not yet fully covered by the
    source candles is dropped rather than emitted partial — call again
    once more source candles are available for it. "Fully covered" is
    judged against each bucket's own real elapsed time for day-aligned
    targets, not a single fixed count, since a bucket spanning a DST
    transition is genuinely 3 or 5 hours long, not the nominal duration.

    Every aggregated candle's `source` is `CandleSource.AGGREGATED`
    (FX-24) — never `NATIVE`, regardless of the source candles' own
    provenance — so it can never silently collide with a native candle
    for the same instrument/granularity/`start_time` in storage.

    Raises `ValueError` if the candles span more than one instrument,
    source granularity, or `source` provenance (FX-24 — aggregating a mix
    of `NATIVE` and `AGGREGATED` source candles together would silently
    blend two potentially differently-aligned datasets; this forces that
    to be a caller error, not a silent blend), or if `into`'s duration
    isn't a whole multiple of the source granularity's duration.
    """
    if not candles:
        return []

    instrument = candles[0].instrument
    source_granularity = candles[0].granularity
    source_provenance = candles[0].source
    for candle in candles:
        if candle.instrument != instrument:
            raise ValueError("all candles must share the same instrument")
        if candle.granularity != source_granularity:
            raise ValueError("all candles must share the same source granularity")
        if candle.source != source_provenance:
            raise ValueError("all candles must share the same source (CandleSource) provenance")

    target_duration = fixed_duration(into)
    source_duration = fixed_duration(source_granularity)
    if target_duration % source_duration != timedelta(0):
        raise ValueError(
            f"{into.value}'s duration is not a whole multiple of {source_granularity.value}'s"
        )
    day_aligned = into in _DAY_ALIGNED_GRANULARITIES

    buckets: dict[datetime, list[Candle]] = defaultdict(list)
    for candle in candles:
        buckets[_bucket_start(candle.start_time.value, into, target_duration)].append(candle)

    aggregated = []
    for bucket_start in sorted(buckets):
        members = sorted(buckets[bucket_start], key=lambda c: c.start_time.value)
        expected_count = _expected_member_count(
            bucket_start, target_duration, source_duration, day_aligned
        )
        if len(members) < expected_count:
            continue
        aggregated.append(_aggregate_bucket(instrument, into, UtcTimestamp(bucket_start), members))

    return aggregated


def _bucket_start(start_time: datetime, granularity: Granularity, duration: timedelta) -> datetime:
    if granularity in _DAY_ALIGNED_GRANULARITIES:
        return _ny_aligned_bucket_start(start_time, duration)
    return _epoch_bucket_start(start_time, duration)


def _epoch_bucket_start(start_time: datetime, duration: timedelta) -> datetime:
    bucket_seconds = duration.total_seconds()
    bucket_index = int(start_time.timestamp() // bucket_seconds)
    return datetime.fromtimestamp(bucket_index * bucket_seconds, tz=start_time.tzinfo)


def _ny_aligned_bucket_start(start_time: datetime, duration: timedelta) -> datetime:
    """The bucket boundary (as a UTC `datetime`) containing `start_time`,
    for a `duration` that evenly divides 24 hours, anchored to 17:00
    `America/New_York`.

    Wall-clock arithmetic throughout: adding `duration` to a
    `zoneinfo`-aware `datetime` advances by that many REAL hours, which
    may render as a different number of wall-clock hours across a DST
    transition (confirmed independently: exactly one 3-hour bucket on the
    spring-forward day, one 5-hour bucket on the fall-back day, every
    other bucket a clean N hours) — this is deliberate, and matches how
    OANDA's own day-aligned candles behave, not a bug to normalize away.
    """
    local = start_time.astimezone(_NY_ZONE)
    day_start = local.replace(hour=_NY_DAILY_ALIGNMENT_HOUR, minute=0, second=0, microsecond=0)
    if local < day_start:
        day_start -= timedelta(days=1)

    if duration == timedelta(days=1):
        return day_start.astimezone(UTC)

    bucket_start = day_start
    while bucket_start + duration <= local:
        bucket_start += duration
    return bucket_start.astimezone(UTC)


def _ny_aligned_bucket_end(bucket_start: datetime, duration: timedelta) -> datetime:
    """The next boundary after `bucket_start` (already a bucket boundary,
    in UTC), `duration` later in `America/New_York` wall-clock terms."""
    local = bucket_start.astimezone(_NY_ZONE)
    return (local + duration).astimezone(UTC)


def _expected_member_count(
    bucket_start: datetime,
    target_duration: timedelta,
    source_duration: timedelta,
    day_aligned: bool,
) -> int:
    if not day_aligned:
        return target_duration // source_duration
    bucket_end = _ny_aligned_bucket_end(bucket_start, target_duration)
    real_span = bucket_end - bucket_start
    return real_span // source_duration


def _aggregate_bucket(
    instrument: Instrument,
    granularity: Granularity,
    start: UtcTimestamp,
    members: list[Candle],
) -> Candle:
    return Candle(
        instrument=instrument,
        granularity=granularity,
        start_time=start,
        bid=_aggregate_ohlc([c.bid for c in members]),
        ask=_aggregate_ohlc([c.ask for c in members]),
        volume=sum(c.volume for c in members),
        is_finalized=all(c.is_finalized for c in members),
        source=CandleSource.AGGREGATED,
    )


def _aggregate_ohlc(ohlcs: list[Ohlc]) -> Ohlc:
    return Ohlc(
        open=ohlcs[0].open,
        high=max(o.high for o in ohlcs),
        low=min(o.low for o in ohlcs),
        close=ohlcs[-1].close,
    )
