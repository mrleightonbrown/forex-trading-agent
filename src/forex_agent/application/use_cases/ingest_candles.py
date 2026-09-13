"""FX-6: the first real use case — wires `MarketDataPort` (fetch) to
`CandleRepository` (persist)."""

from dataclasses import dataclass

from forex_agent.application.ports.candle_repository import CandleRepository
from forex_agent.application.ports.market_data_port import MarketDataPort
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class IngestCandles:
    market_data: MarketDataPort
    candles: CandleRepository

    async def __call__(
        self,
        instrument: Instrument,
        granularity: Granularity,
        start: UtcTimestamp,
        end: UtcTimestamp,
    ) -> int:
        """Fetch [start, end) and persist it. Returns the number of candles
        written. Safe to call repeatedly for an overlapping range — FX-5's
        upsert means re-ingesting is idempotent, not duplicative."""
        fetched = await self.market_data.get_candles(instrument, granularity, start, end)
        return await self.candles.upsert_many(fetched)
