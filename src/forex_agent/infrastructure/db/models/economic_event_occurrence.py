from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from forex_agent.infrastructure.db.base import Base
from forex_agent.infrastructure.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class EconomicEventOccurrenceRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One specific occurrence of a canonical economic event (FX-51;
    identity model revised by FX-51H).

    `occurrence_key` alone is unique -- an occurrence's natural
    identity (see `domain.economic_event_occurrence.
    EconomicEventOccurrence`), never a scheduled timestamp, never a
    provider ID. Every schedule/consensus/actual-value/release vintage
    table below references an occurrence by this SAME natural key via
    a genuine `FOREIGN KEY` constraint, not this row's own UUID `id` --
    the UUID exists only for this project's own DB-wide primary-key
    convention (`UUIDPrimaryKeyMixin`), and is never used as a
    relationship target. `reference_period` is nullable (FX-51H): a
    qualitative/irregular occurrence for which a reference period is
    not a meaningful concept simply has none.
    """

    __tablename__ = "economic_event_occurrences"
    __table_args__ = (
        UniqueConstraint(
            "occurrence_key",
            name="uq_economic_event_occurrences_occurrence_key",
        ),
    )

    occurrence_key: Mapped[str] = mapped_column(String, nullable=False)
    indicator_key: Mapped[str] = mapped_column(String, nullable=False)
    reference_period: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    release_group_key: Mapped[str | None] = mapped_column(String, nullable=True)
