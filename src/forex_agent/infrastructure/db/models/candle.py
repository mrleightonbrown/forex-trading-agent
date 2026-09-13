from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from forex_agent.infrastructure.db.base import Base
from forex_agent.infrastructure.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class CandleRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row per (instrument, granularity, start_time).

    `created_at`/`updated_at` (from `TimestampMixin`) track this *row's*
    bookkeeping — when we first stored it, when we last updated it (e.g. a
    candle finalizing) — separate from `start_time`, the candle's own open
    time in market terms.
    """

    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint(
            "instrument",
            "granularity",
            "start_time",
            name="uq_candles_instrument_granularity_start_time",
        ),
    )

    instrument: Mapped[str] = mapped_column(String, nullable=False)
    granularity: Mapped[str] = mapped_column(String, nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    bid_open: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    bid_high: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    bid_low: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    bid_close: Mapped[Decimal] = mapped_column(Numeric, nullable=False)

    ask_open: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    ask_high: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    ask_low: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    ask_close: Mapped[Decimal] = mapped_column(Numeric, nullable=False)

    volume: Mapped[int] = mapped_column(Integer, nullable=False)
    is_finalized: Mapped[bool] = mapped_column(Boolean, nullable=False)
