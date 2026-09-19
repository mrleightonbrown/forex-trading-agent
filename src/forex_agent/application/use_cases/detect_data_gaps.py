"""FX-8: reads a stored candle range and reports which expected candles are
missing — completing what the pure `find_gaps` domain function alone
couldn't (it needs the candles already fetched)."""

from dataclasses import dataclass

from forex_agent.application.ports.candle_repository import CandleRepository
from forex_agent.domain.candle_boundary import candle_start_boundary
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
        ascending. No market-calendar awareness — see `find_gaps`.

        `start` is snapped down to its own candle boundary before either
        fetching or checking for gaps (found live: a research-dataset gap
        check passing a non-boundary-aligned `start`, e.g. a watermark's
        wall-clock `earliest_ingested`, reported the boundary candle as
        missing even though it existed -- `find_gaps` itself always rounds
        `start` down to the nearest boundary when building its expected
        list, but `CandleRepository.get_range`'s own `start_time >= start`
        filter does not, so a genuinely-present boundary candle could fall
        between the two and be excluded from `stored` while still being
        "expected". Aligning here keeps both calls looking at the same
        window.
        """
        aligned_start = UtcTimestamp(candle_start_boundary(start.value, granularity))
        stored = await self.candles.get_range(instrument, granularity, aligned_start, end)
        return find_gaps(stored, granularity, aligned_start, end)
