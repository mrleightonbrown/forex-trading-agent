"""In-memory `CandleRepository` test double (FX-26), for fast unit tests
of use cases that shouldn't need a live Postgres connection.
"""

from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.timestamps import UtcTimestamp


class FakeCandleRepository:
    """Structurally satisfies `CandleRepository` (a `Protocol`) — no
    inheritance needed; see
    `forex_agent.application.ports.candle_repository`.

    Upserts keyed on (instrument, granularity, start_time, source),
    matching the real `SqlAlchemyCandleRepository`'s unique constraint
    (FX-24) — a native and an aggregated candle for the same slot don't
    collide here either.
    """

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str, object, str], Candle] = {}

    async def upsert_many(self, candles: list[Candle]) -> int:
        for candle in candles:
            key = (
                candle.instrument.symbol,
                candle.granularity.value,
                candle.start_time,
                candle.source.value,
            )
            self._rows[key] = candle
        return len(candles)

    async def get_range(
        self,
        instrument: Instrument,
        granularity: Granularity,
        start: UtcTimestamp,
        end: UtcTimestamp,
    ) -> list[Candle]:
        matching = [
            c
            for c in self._rows.values()
            if c.instrument == instrument
            and c.granularity == granularity
            and start.value <= c.start_time.value < end.value
        ]
        return sorted(matching, key=lambda c: c.start_time.value)
