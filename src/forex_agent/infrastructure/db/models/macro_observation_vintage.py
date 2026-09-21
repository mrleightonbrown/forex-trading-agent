from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from forex_agent.infrastructure.db.base import Base
from forex_agent.infrastructure.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class MacroObservationVintageRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One immutable point-in-time-safe fact for a macro series (FX-41).

    A revision is INSERTED as a new row with a later `released_at` and a
    higher `revision_sequence` -- this table has no application code
    path that UPDATEs `value`, `released_at`, or `revision_sequence` on
    an existing row. `created_at` (from `TimestampMixin`) records when
    this codebase first stored the row -- separate from `released_at`,
    which is the market-knowledge timestamp the point-in-time queries
    actually filter on.

    `(series_key, observation_period, revision_sequence)` is unique --
    it is a vintage's natural identity, and the constraint makes
    inserting the same vintage twice idempotent (raises instead of
    silently duplicating) rather than something callers must
    deduplicate by hand.

    The `ix_..._series_key_released_at` index supports both repository
    query methods, which both filter on `series_key` and
    `released_at <= as_of` before sorting.
    """

    __tablename__ = "macro_observation_vintages"
    __table_args__ = (
        UniqueConstraint(
            "series_key",
            "observation_period",
            "revision_sequence",
            name="uq_macro_observation_vintages_series_period_revision",
        ),
        Index(
            "ix_macro_observation_vintages_series_key_released_at",
            "series_key",
            "released_at",
        ),
    )

    series_key: Mapped[str] = mapped_column(String, nullable=False)
    observation_period: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    released_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revision_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
