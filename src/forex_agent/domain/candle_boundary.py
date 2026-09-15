"""FX-25H: the one canonical definition of "when does a candle of a given
granularity, starting at a given instant, actually close" — extracted
from FX-24's day-aligned aggregation logic after FX-25 independently
reimplemented (and got wrong) its own fixed-duration assumption for H4.
Two interpretations of candle duration existing side by side was the bug;
`candle_aggregation.py` and any strategy reasoning about candle
completion (e.g. `multi_timeframe_trend.py`) now both import from here.

OANDA's day-aligned granularities (`H2`/`H3`/`H4`/`H6`/`H8`/`H12`/`D` —
confirmed live against the practice API, not assumed) anchor to 17:00
`America/New_York`, DST-shifting in UTC terms. `H1` and finer are
unaffected: an hour is a fixed duration with no DST ambiguity
(`America/New_York`'s UTC offset is always a whole number of hours), so
epoch-floored hour buckets already agree with NY-local hour buckets.

A day-aligned candle that contains a DST transition genuinely lasts 3 or
5 real hours, not 4 (or whatever its granularity nominally implies) —
`candle_end_time` reflects that for EVERY day-aligned granularity, not
just whichever one a given caller happens to be using. This is wall-clock
arithmetic throughout: adding a duration to a `zoneinfo`-aware `datetime`
advances the WALL-CLOCK reading by exactly that many hours (e.g. 01:00
EST + 4h = 05:00, always), and it is precisely this wall-clock-fidelity
that makes the corresponding real/UTC-elapsed span become 3 or 5 hours
across a transition — not the other way around. Confirmed independently:
exactly one 3-hour candle on the spring-forward day, one 5-hour candle on
the fall-back day, every other candle a clean N hours. This matches how
OANDA's own day-aligned candles behave, not a bug to normalize away.
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from forex_agent.domain.granularity import Granularity
from forex_agent.domain.granularity_duration import fixed_duration

_NY_ZONE = ZoneInfo("America/New_York")
_NY_DAILY_ALIGNMENT_HOUR = 17  # matches OANDA's own default dailyAlignment=17

DAY_ALIGNED_GRANULARITIES = frozenset(
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


def candle_start_boundary(instant: datetime, granularity: Granularity) -> datetime:
    """The start (UTC) of the `granularity` candle containing `instant`."""
    duration = fixed_duration(granularity)
    if granularity in DAY_ALIGNED_GRANULARITIES:
        return _ny_aligned_start(instant, duration)
    return _epoch_start(instant, duration)


def candle_end_time(start: datetime, granularity: Granularity) -> datetime:
    """The instant (UTC) the `granularity` candle beginning at `start`
    (itself already a valid boundary for that granularity) closes — the
    start of the next candle. DST-aware for day-aligned granularities:
    genuinely 3 or 5 real hours for `H4` on a transition day, not always
    the nominal duration; the source-granularity side of the same
    question, when it's ALSO day-aligned (e.g. `H2` feeding an `H4`
    aggregation), is handled identically — there is no separate "is the
    source itself DST-sensitive" case to special-case.
    """
    duration = fixed_duration(granularity)
    if granularity in DAY_ALIGNED_GRANULARITIES:
        local = start.astimezone(_NY_ZONE)
        return (local + duration).astimezone(UTC)
    return start + duration


def _epoch_start(instant: datetime, duration: timedelta) -> datetime:
    bucket_seconds = duration.total_seconds()
    bucket_index = int(instant.timestamp() // bucket_seconds)
    return datetime.fromtimestamp(bucket_index * bucket_seconds, tz=instant.tzinfo)


def _ny_aligned_start(instant: datetime, duration: timedelta) -> datetime:
    local = instant.astimezone(_NY_ZONE)
    day_start = local.replace(hour=_NY_DAILY_ALIGNMENT_HOUR, minute=0, second=0, microsecond=0)
    if local < day_start:
        day_start -= timedelta(days=1)

    if duration == timedelta(days=1):
        return day_start.astimezone(UTC)

    bucket_start = day_start
    while bucket_start + duration <= local:
        bucket_start += duration
    return bucket_start.astimezone(UTC)
