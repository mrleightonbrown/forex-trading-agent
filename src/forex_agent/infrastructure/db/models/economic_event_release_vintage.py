from datetime import date, datetime, time

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from forex_agent.infrastructure.db.base import Base
from forex_agent.infrastructure.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class EconomicEventReleaseVintageRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One immutable point-in-time-safe release-occurred fact
    (FX-51H) -- see `domain.economic_event_release_vintage.
    EconomicEventReleaseVintage`'s own docstring for the full
    rationale. A correction is INSERTED as a new row with a later
    `availability` and a higher `revision_sequence` -- never an UPDATE
    of an existing one. Same identity/FK/consistency-check shape as
    `EconomicEventScheduleVintageRow`.
    """

    __tablename__ = "economic_event_release_vintages"
    __table_args__ = (
        UniqueConstraint(
            "occurrence_key",
            "revision_sequence",
            name="uq_economic_event_release_vintages_identity",
        ),
        ForeignKeyConstraint(
            ["occurrence_key"],
            ["economic_event_occurrences.occurrence_key"],
            name="fk_economic_event_release_vintages_occurrence",
        ),
        Index(
            "ix_economic_event_release_vintages_occurrence_availability",
            "occurrence_key",
            "availability",
        ),
        CheckConstraint(
            "(availability IS NULL) = (availability_confidence = 'UNKNOWN')",
            name="ck_economic_event_release_vintages_avail_confidence",
        ),
    )

    occurrence_key: Mapped[str] = mapped_column(String, nullable=False)
    revision_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    released_date: Mapped[date] = mapped_column(Date, nullable=False)
    released_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    released_timezone: Mapped[str] = mapped_column(String, nullable=False)
    availability: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    availability_confidence: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
