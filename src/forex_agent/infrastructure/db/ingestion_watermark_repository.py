"""SQLAlchemy implementation of `IngestionWatermarkRepository` (FX-26,
`acquire_lock`/`release_lock` FX-31)."""

import hashlib
import struct

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.models.ingestion_watermark import IngestionWatermarkRow

_CONFLICT_KEY = ("instrument", "granularity")


def _advisory_lock_key(instrument: Instrument, granularity: Granularity) -> int:
    """A stable (not process-salted, unlike Python's own `hash()`) 64-bit
    signed key for Postgres' `pg_advisory_lock`/`pg_advisory_unlock`,
    derived from `(instrument, granularity)` — the same pair
    `set_watermark` keys a row on."""
    digest = hashlib.sha256(f"{instrument.symbol}:{granularity.value}".encode()).digest()
    (key,) = struct.unpack(">q", digest[:8])
    return int(key)


class SqlAlchemyIngestionWatermarkRepository:
    """Implements `IngestionWatermarkRepository` via a Postgres
    `ON CONFLICT DO UPDATE` upsert, keyed on (instrument, granularity) —
    exactly one watermark row per series, replaced wholesale on each
    `set_watermark` call."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_watermark(
        self, instrument: Instrument, granularity: Granularity
    ) -> tuple[UtcTimestamp, UtcTimestamp] | None:
        stmt = select(IngestionWatermarkRow).where(
            IngestionWatermarkRow.instrument == instrument.symbol,
            IngestionWatermarkRow.granularity == granularity.value,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None
        return UtcTimestamp(row.earliest_ingested), UtcTimestamp(row.latest_ingested)

    async def set_watermark(
        self,
        instrument: Instrument,
        granularity: Granularity,
        earliest: UtcTimestamp,
        latest: UtcTimestamp,
    ) -> None:
        stmt = pg_insert(IngestionWatermarkRow).values(
            instrument=instrument.symbol,
            granularity=granularity.value,
            earliest_ingested=earliest.value,
            latest_ingested=latest.value,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=_CONFLICT_KEY,
            set_={
                "earliest_ingested": stmt.excluded.earliest_ingested,
                "latest_ingested": stmt.excluded.latest_ingested,
            },
        )
        await self._session.execute(stmt)
        await self._session.commit()

    async def acquire_lock(self, instrument: Instrument, granularity: Granularity) -> None:
        # Session-level (not transaction-scoped) -- survives the many
        # per-page commits BackfillCandles makes over the lock's
        # lifetime; released explicitly by `release_lock`, or by
        # Postgres automatically if the session's connection ever
        # closes without that.
        await self._session.execute(
            text("SELECT pg_advisory_lock(:key)"),
            {"key": _advisory_lock_key(instrument, granularity)},
        )

    async def release_lock(self, instrument: Instrument, granularity: Granularity) -> None:
        await self._session.execute(
            text("SELECT pg_advisory_unlock(:key)"),
            {"key": _advisory_lock_key(instrument, granularity)},
        )
