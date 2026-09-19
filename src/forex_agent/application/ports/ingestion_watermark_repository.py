from typing import Protocol

from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.timestamps import UtcTimestamp


class IngestionWatermarkRepository(Protocol):
    """Tracks how much of one (instrument, granularity) NATIVE candle
    series has been durably ingested — FX-26's resumability mechanism.

    One contiguous covered interval per (instrument, granularity): the
    watermark *is* the resume state, not a separate log of completed
    jobs — a caller doesn't need to remember any particular backfill
    request's own parameters to resume it, just re-issue any request
    that overlaps or touches the current interval.
    """

    async def get_watermark(
        self, instrument: Instrument, granularity: Granularity
    ) -> tuple[UtcTimestamp, UtcTimestamp] | None:
        """`(earliest_ingested, latest_ingested)` for this series, or
        `None` if nothing has been ingested yet."""
        ...

    async def set_watermark(
        self,
        instrument: Instrument,
        granularity: Granularity,
        earliest: UtcTimestamp,
        latest: UtcTimestamp,
    ) -> None:
        """Replace the stored watermark for this series with
        `(earliest, latest)` — an upsert, not an incremental update; the
        caller is responsible for computing the correct new bounds."""
        ...
