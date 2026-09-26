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


class EconomicEventScheduleVintageRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One immutable point-in-time-safe schedule fact (FX-51). A
    reschedule/postponement/cancellation/reinstatement is INSERTED as a
    new row with a later `availability` and a higher `revision_
    sequence` -- this table has no application code path that UPDATEs
    an existing row.

    `(indicator_key, reference_period, revision_sequence)` is unique --
    the natural identity of one schedule vintage, making a duplicate
    insert idempotent (matching `MacroObservationVintageRow`'s own
    identity shape, FX-41). `(indicator_key, reference_period)`
    together also carry a genuine `FOREIGN KEY` into
    `economic_event_occurrences`' own unique constraint -- an
    occurrence must exist before any vintage of it can be recorded.

    `ck_..._availability_confidence_consistency` mirrors the domain
    layer's own `require_availability_consistency` check
    (`domain._guards`) in storage, so the invariant holds even for a
    row written by a future path that bypasses the domain constructor.
    """

    __tablename__ = "economic_event_schedule_vintages"
    __table_args__ = (
        UniqueConstraint(
            "indicator_key",
            "reference_period",
            "revision_sequence",
            name="uq_economic_event_schedule_vintages_identity",
        ),
        ForeignKeyConstraint(
            ["indicator_key", "reference_period"],
            [
                "economic_event_occurrences.indicator_key",
                "economic_event_occurrences.reference_period",
            ],
            name="fk_economic_event_schedule_vintages_occurrence",
        ),
        Index(
            "ix_economic_event_schedule_vintages_occurrence_availability",
            "indicator_key",
            "reference_period",
            "availability",
        ),
        CheckConstraint(
            "(availability IS NULL) = (availability_confidence = 'UNKNOWN')",
            name="ck_economic_event_schedule_vintages_avail_confidence",
        ),
    )

    indicator_key: Mapped[str] = mapped_column(String, nullable=False)
    reference_period: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revision_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False)
    scheduled_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    schedule_timezone: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    availability: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    availability_confidence: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
