"""SQLAlchemy implementation of `IngestionWatermarkRepository` (FX-26)."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.models.ingestion_watermark import IngestionWatermarkRow

_CONFLICT_KEY = ("instrument", "granularity")


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
