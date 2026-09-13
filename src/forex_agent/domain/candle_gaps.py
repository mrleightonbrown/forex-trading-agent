"""FX-8: gap detection — pure, no I/O.

Deliberately no market-calendar awareness (weekends/holidays aren't
excluded): forex session boundaries shift with daylight saving and vary by
broker, which is real complexity this cuts rather than approximates badly.
Callers should pass ranges already known to be within a trading session.
"""

from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.granularity_duration import fixed_duration
from forex_agent.domain.timestamps import UtcTimestamp


def find_gaps(
    candles: list[Candle],
    granularity: Granularity,
    start: UtcTimestamp,
    end: UtcTimestamp,
) -> list[UtcTimestamp]:
    """Expected candle start times within [start, end) at `granularity`'s
    fixed duration that are *not* present in `candles`, sorted ascending.

    `candles` need not already be filtered to one instrument — this
    function only looks at `start_time`. Raises `ValueError` if any candle
    doesn't match `granularity`.
    """
    for candle in candles:
        if candle.granularity != granularity:
            raise ValueError(
                f"candle at {candle.start_time.value.isoformat()} has granularity "
                f"{candle.granularity.value}, expected {granularity.value}"
            )

    present = {candle.start_time for candle in candles}
    duration = fixed_duration(granularity)

    expected = []
    cursor = start.value
    while cursor < end.value:
        expected.append(UtcTimestamp(cursor))
        cursor += duration

    return [ts for ts in expected if ts not in present]
