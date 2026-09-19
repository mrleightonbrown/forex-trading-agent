"""In-memory `IngestionWatermarkRepository` test double (FX-26).

`acquire_lock`/`release_lock` moved out to `FakeBackfillLock` (FX-31H) --
see that module and `infrastructure/db/backfill_lock.py` for why."""

from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.timestamps import UtcTimestamp


class FakeIngestionWatermarkRepository:
    """Structurally satisfies `IngestionWatermarkRepository` (a
    `Protocol`) — no inheritance needed; see
    `forex_agent.application.ports.ingestion_watermark_repository`."""

    def __init__(self) -> None:
        self._watermarks: dict[tuple[str, str], tuple[UtcTimestamp, UtcTimestamp]] = {}

    async def get_watermark(
        self, instrument: Instrument, granularity: Granularity
    ) -> tuple[UtcTimestamp, UtcTimestamp] | None:
        return self._watermarks.get((instrument.symbol, granularity.value))

    async def set_watermark(
        self,
        instrument: Instrument,
        granularity: Granularity,
        earliest: UtcTimestamp,
        latest: UtcTimestamp,
    ) -> None:
        self._watermarks[(instrument.symbol, granularity.value)] = (earliest, latest)
