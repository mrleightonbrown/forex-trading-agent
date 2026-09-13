"""FX-7: pure candle aggregation — no I/O, no repository access.

Reading source candles back out of storage and persisting aggregates is a
separate concern (a future use case), not built here.
"""

from collections import defaultdict
from datetime import datetime, timedelta

from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.granularity_duration import fixed_duration
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.timestamps import UtcTimestamp


def aggregate_candles(candles: list[Candle], into: Granularity) -> list[Candle]:
    """Group `candles` (must share one instrument and one source
    granularity) into fixed-duration buckets at `into`'s duration, and
    produce one aggregated candle per *complete* bucket.

    A trailing bucket not yet fully covered by the source candles is
    dropped rather than emitted partial — call again once more source
    candles are available for it.

    Raises `ValueError` if the candles span more than one instrument or
    source granularity, or if `into`'s duration isn't a whole multiple of
    the source granularity's duration.
    """
    if not candles:
        return []

    instrument = candles[0].instrument
    source_granularity = candles[0].granularity
    for candle in candles:
        if candle.instrument != instrument:
            raise ValueError("all candles must share the same instrument")
        if candle.granularity != source_granularity:
            raise ValueError("all candles must share the same source granularity")

    target_duration = fixed_duration(into)
    source_duration = fixed_duration(source_granularity)
    if target_duration % source_duration != timedelta(0):
        raise ValueError(
            f"{into.value}'s duration is not a whole multiple of {source_granularity.value}'s"
        )
    candles_per_bucket = target_duration // source_duration

    buckets: dict[datetime, list[Candle]] = defaultdict(list)
    for candle in candles:
        buckets[_bucket_start(candle.start_time.value, target_duration)].append(candle)

    aggregated = []
    for bucket_start in sorted(buckets):
        members = sorted(buckets[bucket_start], key=lambda c: c.start_time.value)
        if len(members) < candles_per_bucket:
            continue
        aggregated.append(_aggregate_bucket(instrument, into, UtcTimestamp(bucket_start), members))

    return aggregated


def _bucket_start(start_time: datetime, duration: timedelta) -> datetime:
    bucket_seconds = duration.total_seconds()
    bucket_index = int(start_time.timestamp() // bucket_seconds)
    return datetime.fromtimestamp(bucket_index * bucket_seconds, tz=start_time.tzinfo)


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
    )


def _aggregate_ohlc(ohlcs: list[Ohlc]) -> Ohlc:
    return Ohlc(
        open=ohlcs[0].open,
        high=max(o.high for o in ohlcs),
        low=min(o.low for o in ohlcs),
        close=ohlcs[-1].close,
    )
