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

    `candles` must all belong to one instrument — FX-11H: a candle from a
    different instrument must never be able to fill another instrument's
    expected slot. Raises `ValueError` if any candle doesn't match
    `granularity`, or if the candles span more than one instrument.
    """
    instrument = candles[0].instrument if candles else None
    for candle in candles:
        if candle.granularity != granularity:
            raise ValueError(
                f"candle at {candle.start_time.value.isoformat()} has granularity "
                f"{candle.granularity.value}, expected {granularity.value}"
            )
        if candle.instrument != instrument:
            raise ValueError(
                "all candles must belong to one instrument; found "
                f"{candle.instrument.symbol} and {instrument.symbol if instrument else '?'}"
            )

    present = {candle.start_time for candle in candles}
    duration = fixed_duration(granularity)

    expected = []
    cursor = start.value
    while cursor < end.value:
        expected.append(UtcTimestamp(cursor))
        cursor += duration

    return [ts for ts in expected if ts not in present]
