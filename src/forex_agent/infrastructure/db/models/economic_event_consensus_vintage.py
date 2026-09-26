from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from forex_agent.infrastructure.db.base import Base
from forex_agent.infrastructure.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class EconomicEventConsensusVintageRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One immutable point-in-time-safe consensus/forecast fact
    (FX-51). A revised consensus is INSERTED as a new row with a later
    `availability` and a higher `revision_sequence` -- never an UPDATE
    of an existing one. See `EconomicEventScheduleVintageRow` for the
    identical identity/FK/consistency-check shape this table mirrors.
    """

    __tablename__ = "economic_event_consensus_vintages"
    __table_args__ = (
        UniqueConstraint(
            "indicator_key",
            "reference_period",
            "revision_sequence",
            name="uq_economic_event_consensus_vintages_identity",
        ),
        ForeignKeyConstraint(
            ["indicator_key", "reference_period"],
            [
                "economic_event_occurrences.indicator_key",
                "economic_event_occurrences.reference_period",
            ],
            name="fk_economic_event_consensus_vintages_occurrence",
        ),
        Index(
            "ix_economic_event_consensus_vintages_occurrence_availability",
            "indicator_key",
            "reference_period",
            "availability",
        ),
        CheckConstraint(
            "(availability IS NULL) = (availability_confidence = 'UNKNOWN')",
            name="ck_economic_event_consensus_vintages_avail_confidence",
        ),
    )

    indicator_key: Mapped[str] = mapped_column(String, nullable=False)
    reference_period: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revision_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    consensus_value: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    availability: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    availability_confidence: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    raw_source_value: Mapped[str | None] = mapped_column(String, nullable=True)
