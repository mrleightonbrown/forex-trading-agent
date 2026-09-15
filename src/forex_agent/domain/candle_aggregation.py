"""FX-7 (day-aligned bucketing fixed FX-24, boundary logic canonicalized
FX-25H): pure candle aggregation — no I/O, no repository access.

Reading source candles back out of storage and persisting aggregates is a
separate concern (a future use case), not built here.

FX-25H: "is this bucket complete" used to be a member COUNT check
(`target_duration // source_duration`, or a DST-adjusted real-time
variant of the same idea). That breaks when the SOURCE granularity is
itself day-aligned (e.g. `H2` feeding an `H4` aggregation): a DST
transition can shorten one of the source candles too, so the true
expected count isn't simply `real_span // source_duration` — verified
directly (the spring-forward `H4` bucket 06:00-09:00Z, 3 real hours,
needs a 1-hour `H2` candle followed by a normal 2-hour one; naive
division gives 1, not the correct 2). It also silently accepted a
duplicate-plus-missing source candle at the RIGHT count but the WRONG
shape (the original FX-7 edge case: `12:00,12:01,12:02,12:02,12:04` —
five records, but `12:03` is missing and `12:02` doubled).

Completeness is now judged by generating the EXACT expected source
candle start-times for a bucket (via `candle_boundary.candle_end_time`,
walked forward one source candle at a time) and requiring the actual
member start-times to match that sequence exactly — count, gaps, and
duplicates are all covered by the same check.

FX-25H.1: that walk also has to verify the LAST source candle lands
exactly on the target bucket's own end — nominal divisibility
(`target_duration % source_duration == 0`) does not guarantee NY
wall-clock source boundaries stay nested inside the target boundary
across a DST discontinuity. Verified directly: the spring-forward `H6`
bucket 04:00-09:00Z (5 real hours) is nominally divisible by `H3` (3h),
but `H3`'s own DST-shortened boundary that day falls at 07:00-10:00Z —
straddling the `H6` boundary by an hour, not nested inside it. Without
checking exact termination, `aggregate_candles` would silently pull an
hour of data from OUTSIDE the target bucket into its aggregate (a real,
reproduced contamination/look-ahead, not hypothetical). A target bucket
whose source candles don't exactly tile it — front-to-back, no gap, no
overhang — is dropped, same as a genuinely incomplete one; this is a
property of that specific DST-transition bucket, not a reason to reject
the granularity pairing generally (an ordinary, non-transition `H3`→`H6`
bucket tiles perfectly).
"""

from collections import defaultdict
from datetime import datetime, timedelta

from forex_agent.domain.candle import Candle
from forex_agent.domain.candle_boundary import candle_end_time, candle_start_boundary
from forex_agent.domain.candle_source import CandleSource
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.granularity_duration import fixed_duration
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.timestamps import UtcTimestamp


def aggregate_candles(candles: list[Candle], into: Granularity) -> list[Candle]:
    """Group `candles` (must share one instrument and one source
    granularity) into `into`-duration buckets, and produce one aggregated
    candle per *complete* bucket.

    Buckets for `into` in `H2`/`H3`/`H4`/`H6`/`H8`/`H12`/`D` are anchored
    to 17:00 `America/New_York` (FX-24), matching OANDA's own native
    candles for those granularities — DST-aware via
    `candle_boundary.candle_start_boundary`, not a fixed UTC duration
    walked from the Unix epoch. Every other target granularity keeps the
    original epoch-UTC-floored fixed-duration bucketing (`H1` and finer
    have no DST ambiguity to account for).

    A trailing, DST-shortened, gappy/duplicated, or (FX-25H.1)
    non-exactly-tiling bucket is dropped rather than emitted wrong — call
    again once the source candles for it are complete. "Complete"
    (FX-25H) means the bucket's actual member start-times exactly match
    the expected source-candle boundary sequence for that bucket,
    generated via `candle_boundary.candle_end_time` — not a member
    count, which can't distinguish a genuinely short DST bucket from a
    bucket that's merely missing data, nor catch a duplicate-plus-missing
    pair at the right total count. That expected sequence is itself only
    valid (FX-25H.1) if its last source candle ends EXACTLY at the
    target bucket's own end — nominal divisibility between granularities
    doesn't guarantee that across a DST discontinuity; a bucket whose
    source candles would straddle rather than exactly tile it is dropped
    too, rather than aggregated from data that overhangs the boundary.

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

    buckets: dict[datetime, list[Candle]] = defaultdict(list)
    for candle in candles:
        buckets[candle_start_boundary(candle.start_time.value, into)].append(candle)

    aggregated = []
    for bucket_start in sorted(buckets):
        members = sorted(buckets[bucket_start], key=lambda c: c.start_time.value)
        actual_starts = [m.start_time.value for m in members]
        expected_starts = _expected_source_starts(bucket_start, into, source_granularity)
        if actual_starts != expected_starts:
            continue
        aggregated.append(_aggregate_bucket(instrument, into, UtcTimestamp(bucket_start), members))

    return aggregated


def _expected_source_starts(
    bucket_start: datetime, target_granularity: Granularity, source_granularity: Granularity
) -> list[datetime] | None:
    """The exact sequence of source-candle start-times a COMPLETE
    `target_granularity` bucket beginning at `bucket_start` must contain
    — walked one source candle at a time via `candle_end_time`, so a
    DST-shortened/lengthened source candle (when the source is itself
    day-aligned) is accounted for exactly, not assumed away by a fixed
    per-bucket count.

    Returns `None` (FX-25H.1) if the walk overshoots or undershoots the
    target bucket's own end — i.e. the source candles for this specific
    bucket don't exactly tile it, front to back, which nominal duration
    divisibility alone doesn't guarantee across a DST discontinuity. The
    caller treats `None` exactly like "incomplete": drop this bucket.
    """
    bucket_end = candle_end_time(bucket_start, target_granularity)
    starts = []
    cursor = bucket_start
    while cursor < bucket_end:
        starts.append(cursor)
        cursor = candle_end_time(cursor, source_granularity)
    if cursor != bucket_end:
        return None
    return starts


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
