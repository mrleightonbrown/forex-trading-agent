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

    async def acquire_lock(self, instrument: Instrument, granularity: Granularity) -> None:
        """Blocks until this series' watermark is exclusively held by
        the caller (FX-31). `BackfillCandles` holds this for the
        duration of a whole backfill call — not just one `set_watermark`
        — so two concurrent backfills for the same series are
        serialized (the second blocks until the first fully completes)
        rather than racing: reading the same starting watermark,
        computing conflicting page plans, and one's `set_watermark`
        calls silently clobbering the other's.
        """
        ...

    async def release_lock(self, instrument: Instrument, granularity: Granularity) -> None:
        """Releases a lock acquired via `acquire_lock`. Must be called
        even if the caller's own work raised — see `BackfillCandles`'s
        `try`/`finally`."""
        ...
