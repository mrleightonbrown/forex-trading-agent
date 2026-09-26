from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from forex_agent.infrastructure.db.base import Base
from forex_agent.infrastructure.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class EconomicEventOccurrenceRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One specific occurrence of a canonical economic event (FX-51).

    `(indicator_key, reference_period)` is unique -- an occurrence's
    natural identity (see `domain.economic_event_occurrence.
    EconomicEventOccurrence`), never a scheduled timestamp. Every
    schedule/consensus/actual-value vintage table below references an
    occurrence by this SAME composite natural key via a genuine
    `FOREIGN KEY` constraint, not this row's own UUID `id` -- the UUID
    exists only for this project's own DB-wide primary-key convention
    (`UUIDPrimaryKeyMixin`), and is never used as a relationship target.
    """

    __tablename__ = "economic_event_occurrences"
    __table_args__ = (
        UniqueConstraint(
            "indicator_key",
            "reference_period",
            name="uq_economic_event_occurrences_indicator_reference_period",
        ),
    )

    indicator_key: Mapped[str] = mapped_column(String, nullable=False)
    reference_period: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    release_group_key: Mapped[str | None] = mapped_column(String, nullable=True)
