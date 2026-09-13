"""FX-7 (persistence half): reads source candles, aggregates them, persists
the result — completing what the pure `aggregate_candles` domain function
deliberately left out."""

from dataclasses import dataclass

from forex_agent.application.ports.candle_repository import CandleRepository
from forex_agent.domain.candle_aggregation import aggregate_candles
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class AggregateCandles:
    candles: CandleRepository

    async def __call__(
        self,
        instrument: Instrument,
        source_granularity: Granularity,
        into: Granularity,
        start: UtcTimestamp,
        end: UtcTimestamp,
    ) -> int:
        """Read [start, end) of `source_granularity` candles, aggregate into
        `into`, persist the result. Safe to call repeatedly — FX-5's upsert
        means re-aggregating is idempotent, not duplicative. Returns the
        number of aggregated candles written."""
        source = await self.candles.get_range(instrument, source_granularity, start, end)
        aggregated = aggregate_candles(source, into)
        return await self.candles.upsert_many(aggregated)
