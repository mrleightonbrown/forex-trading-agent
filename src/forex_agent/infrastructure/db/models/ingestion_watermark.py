from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from forex_agent.infrastructure.db.base import Base
from forex_agent.infrastructure.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class IngestionWatermarkRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row per (instrument, granularity) — the FX-26 resumability
    watermark. `earliest_ingested`/`latest_ingested` describe one
    contiguous covered interval for that series' NATIVE candles; there is
    deliberately no `source` column here — this table only tracks the
    provider-backfill pipeline (FX-26), not `aggregate_candles`' output.
    """

    __tablename__ = "ingestion_watermarks"
    __table_args__ = (
        UniqueConstraint(
            "instrument",
            "granularity",
            name="uq_ingestion_watermarks_instrument_granularity",
        ),
    )

    instrument: Mapped[str] = mapped_column(String, nullable=False)
    granularity: Mapped[str] = mapped_column(String, nullable=False)
    earliest_ingested: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latest_ingested: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
