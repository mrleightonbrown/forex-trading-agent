"""FX-8: reads a stored candle range and reports which expected candles are
missing — completing what the pure `find_gaps` domain function alone
couldn't (it needs the candles already fetched)."""

from dataclasses import dataclass

from forex_agent.application.ports.candle_repository import CandleRepository
from forex_agent.domain.candle_gaps import find_gaps
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class DetectDataGaps:
    candles: CandleRepository

    async def __call__(
        self,
        instrument: Instrument,
        granularity: Granularity,
        start: UtcTimestamp,
        end: UtcTimestamp,
    ) -> list[UtcTimestamp]:
        """Missing expected candle start times within [start, end), sorted
        ascending. No market-calendar awareness — see `find_gaps`."""
        stored = await self.candles.get_range(instrument, granularity, start, end)
        return find_gaps(stored, granularity, start, end)
