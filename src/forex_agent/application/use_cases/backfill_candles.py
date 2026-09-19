"""FX-26: paginated, resumable historical backfill.

`IngestCandles` (FX-6) is bounded to whatever fits in one `MarketDataPort.
get_candles` request (OANDA's own 5000-candle cap). This splits
arbitrarily large ranges into safe pages via `candle_pagination.
split_into_pages`, and tracks progress durably via
`IngestionWatermarkRepository` so an interrupted backfill resumes without
re-fetching or duplicating already-completed pages.

The watermark IS the resume state — there is no separate "job" object or
resume flag. Every call recomputes what's still missing from the current
watermark and the requested `[start, end)`, then fetches only that. A
crash mid-backfill simply leaves the watermark reflecting exactly the
pages that truly completed (updated after each page, not before); the
next call — with the same or a different range — picks up correctly.

A request that doesn't overlap or touch the existing watermark interval
raises `ValueError` rather than silently extending the stored interval
across a gap that was never actually fetched — a single contiguous
interval can't represent two disjoint covered ranges, and pretending
otherwise would be a real correctness bug, not a convenience. Backward
and forward extensions are each fetched as their own paginated
sub-operation; a request needing both is handled as two, backward first.

FX-30: the watermark's own `earliest_ingested`/`latest_ingested` are now
always genuine candle boundaries, not whatever literal `start`/`end` a
caller happened to pass in (e.g. a wall-clock `datetime.now()`, which is
almost never exactly on an hour). FX-27H.1 caught this indirectly (a
misaligned `earliest_ingested` made `DetectDataGaps` report a false-
positive gap); this closes it at the source instead of leaving every
future consumer to defend against it individually. Both bounds are
FLOORED (via `candle_boundary.candle_start_boundary`), never rounded up:
flooring `earliest` is just "the first candle we can vouch for starts no
earlier than this"; flooring `latest` matters more subtly — a requested
`end` is very often "now", almost always mid-candle, and the candle
containing it may still be forming. Rounding `latest` UP to that candle's
close would claim coverage of a candle that might not exist yet; flooring
it instead means the watermark only ever claims candles that are already
fully behind the requested `end`. This changes NOTHING about what's
actually fetched from the provider (`split_into_pages` already computes
its own page boundaries the same way it always did) — only what gets
recorded as covered.

FX-31 (connection-pinning correction FX-31H): concurrent backfills for
the same series are serialized via a `BackfillLock`, held for the whole
call. FX-31's first attempt put this lock on `IngestionWatermarkRepository`
itself, backed by a Postgres advisory lock issued through the SAME
session this class's `candles`/`watermarks` ports use — broken, because
that session's underlying connection changes across the per-page commits
`upsert_many`/`set_watermark` make, and a Postgres advisory lock belongs
to the physical connection, not the session object. `BackfillLock` is a
separate port specifically so its real implementation can pin one
dedicated connection for the lock's entire duration, independent of
whatever connection churn the watermark/candle repositories go through.
"""

from dataclasses import dataclass

from forex_agent.application.ports.backfill_lock import BackfillLock
from forex_agent.application.ports.candle_repository import CandleRepository
from forex_agent.application.ports.ingestion_watermark_repository import (
    IngestionWatermarkRepository,
)
from forex_agent.application.ports.market_data_port import MarketDataPort
from forex_agent.domain.candle_boundary import candle_start_boundary
from forex_agent.domain.candle_pagination import split_into_pages
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.timestamps import UtcTimestamp

# Matches OANDA's own per-request cap (FX-6) — a plain application-layer
# constant, not imported from infrastructure/broker_oanda/ (apps ->
# application -> domain must not run backwards).
DEFAULT_MAX_CANDLES_PER_PAGE = 5000


@dataclass(frozen=True, slots=True)
class BackfillResult:
    pages_fetched: int
    candles_written: int
    earliest_ingested: UtcTimestamp
    latest_ingested: UtcTimestamp


@dataclass(frozen=True, slots=True)
class BackfillCandles:
    market_data: MarketDataPort
    candles: CandleRepository
    watermarks: IngestionWatermarkRepository
    lock: BackfillLock
    max_candles_per_page: int = DEFAULT_MAX_CANDLES_PER_PAGE

    async def __call__(
        self,
        instrument: Instrument,
        granularity: Granularity,
        start: UtcTimestamp,
        end: UtcTimestamp,
    ) -> BackfillResult:
        if end.value <= start.value:
            raise ValueError("end must be after start")

        # Held for this whole call, not just one set_watermark -- serializes
        # concurrent backfills for the same series (the second blocks until
        # the first fully completes) instead of letting them race: read the
        # same starting watermark, compute conflicting page plans, and
        # clobber each other's progress. Irrelevant to a sequential one-off
        # dataset load, but matters once anything schedules backfills
        # automatically.
        async with self.lock.acquire(instrument, granularity):
            existing = await self.watermarks.get_watermark(instrument, granularity)
            pages_fetched = 0
            candles_written = 0

            if existing is None:
                floor_earliest = UtcTimestamp(candle_start_boundary(start.value, granularity))
                pages, written = await self._extend_forward(
                    instrument, granularity, start, end, floor_earliest=floor_earliest
                )
                pages_fetched += pages
                candles_written += written
            else:
                existing_earliest, existing_latest = existing
                touches = (
                    start.value <= existing_latest.value and existing_earliest.value <= end.value
                )
                if not touches:
                    raise ValueError(
                        f"requested range [{start.value.isoformat()}, {end.value.isoformat()}) "
                        "does not overlap or touch the currently ingested range "
                        f"[{existing_earliest.value.isoformat()}, "
                        f"{existing_latest.value.isoformat()}) for {instrument.symbol} "
                        f"{granularity.value}; backfilling a disjoint historical period isn't "
                        "supported by a single contiguous watermark -- request a range that "
                        "bridges the gap instead"
                    )

                if start.value < existing_earliest.value:
                    pages, written = await self._extend_backward(
                        instrument,
                        granularity,
                        start,
                        existing_earliest,
                        ceiling_latest=existing_latest,
                    )
                    pages_fetched += pages
                    candles_written += written

                if end.value > existing_latest.value:
                    current = await self.watermarks.get_watermark(instrument, granularity)
                    assert current is not None
                    pages, written = await self._extend_forward(
                        instrument, granularity, existing_latest, end, floor_earliest=current[0]
                    )
                    pages_fetched += pages
                    candles_written += written

            final = await self.watermarks.get_watermark(instrument, granularity)
            assert final is not None
            return BackfillResult(pages_fetched, candles_written, final[0], final[1])

    async def _extend_forward(
        self,
        instrument: Instrument,
        granularity: Granularity,
        range_start: UtcTimestamp,
        range_end: UtcTimestamp,
        floor_earliest: UtcTimestamp,
    ) -> tuple[int, int]:
        """Fetches `[range_start, range_end)` in ascending page order,
        advancing the watermark's `latest` bound page by page while
        holding `earliest` fixed at `floor_earliest`."""
        pages_fetched = 0
        candles_written = 0
        for page in split_into_pages(
            range_start, range_end, granularity, self.max_candles_per_page
        ):
            fetched = await self.market_data.get_candles(
                instrument, granularity, page.start, page.end
            )
            candles_written += await self.candles.upsert_many(fetched)
            pages_fetched += 1
            # FX-30: floor to a genuine boundary -- only the LAST page's
            # `.end` can ever be non-aligned (clamped to a raw, possibly
            # mid-candle `range_end`); flooring an already-aligned value
            # is a no-op, so this is safe to apply unconditionally.
            aligned_latest = UtcTimestamp(candle_start_boundary(page.end.value, granularity))
            await self.watermarks.set_watermark(
                instrument, granularity, floor_earliest, aligned_latest
            )
        return pages_fetched, candles_written

    async def _extend_backward(
        self,
        instrument: Instrument,
        granularity: Granularity,
        range_start: UtcTimestamp,
        range_end: UtcTimestamp,
        ceiling_latest: UtcTimestamp,
    ) -> tuple[int, int]:
        """Fetches `[range_start, range_end)` in DESCENDING page order —
        closest to the already-covered boundary first — so `earliest`
        only ever retreats into contiguous, already-verified territory;
        a crash partway through never leaves a silent gap between the
        newly-fetched pages and the pre-existing coverage."""
        pages_fetched = 0
        candles_written = 0
        pages = split_into_pages(range_start, range_end, granularity, self.max_candles_per_page)
        for page in reversed(pages):
            fetched = await self.market_data.get_candles(
                instrument, granularity, page.start, page.end
            )
            candles_written += await self.candles.upsert_many(fetched)
            pages_fetched += 1
            await self.watermarks.set_watermark(instrument, granularity, page.start, ceiling_latest)
        return pages_fetched, candles_written
