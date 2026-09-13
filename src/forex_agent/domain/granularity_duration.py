from datetime import timedelta

from forex_agent.domain.granularity import Granularity

_FIXED_DURATIONS: dict[Granularity, timedelta] = {
    Granularity.S5: timedelta(seconds=5),
    Granularity.S10: timedelta(seconds=10),
    Granularity.S15: timedelta(seconds=15),
    Granularity.S30: timedelta(seconds=30),
    Granularity.M1: timedelta(minutes=1),
    Granularity.M2: timedelta(minutes=2),
    Granularity.M4: timedelta(minutes=4),
    Granularity.M5: timedelta(minutes=5),
    Granularity.M10: timedelta(minutes=10),
    Granularity.M15: timedelta(minutes=15),
    Granularity.M30: timedelta(minutes=30),
    Granularity.H1: timedelta(hours=1),
    Granularity.H2: timedelta(hours=2),
    Granularity.H3: timedelta(hours=3),
    Granularity.H4: timedelta(hours=4),
    Granularity.H6: timedelta(hours=6),
    Granularity.H8: timedelta(hours=8),
    Granularity.H12: timedelta(hours=12),
    Granularity.D: timedelta(days=1),
    # W (week) and M (month) are deliberately excluded: not a fixed
    # duration (a month varies), so bucket-boundary math doesn't apply the
    # same way. Aggregating into them isn't supported yet.
}


def fixed_duration(granularity: Granularity) -> timedelta:
    try:
        return _FIXED_DURATIONS[granularity]
    except KeyError:
        raise ValueError(
            f"{granularity.value} has no fixed duration and cannot be used as an "
            "aggregation target or source"
        ) from None
