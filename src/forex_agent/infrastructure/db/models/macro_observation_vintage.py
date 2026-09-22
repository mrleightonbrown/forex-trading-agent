from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from forex_agent.infrastructure.db.base import Base
from forex_agent.infrastructure.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class MacroObservationVintageRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One immutable point-in-time-safe fact for a macro series (FX-41).

    A revision is INSERTED as a new row with a later `released_at` and a
    higher `revision_sequence` -- this table has no application code
    path that UPDATEs `value` or `revision_sequence` on an existing row.
    `created_at` (from `TimestampMixin`) records when this codebase
    first stored the row -- separate from `released_at`, which is the
    market-knowledge timestamp the point-in-time queries actually
    filter on. FX-43H's `replace_provisional_release_timing` is the ONE
    narrowly-scoped exception: an atomic conditional UPDATE (FX-43H.1)
    that only ever touches `released_at`/`effective_at`/`released_at_
    is_verified`, and only on a row still marked provisional (its own
    `WHERE released_at_is_verified = false` predicate) -- it has no
    `value` parameter at all, so a genuine economic-value change is
    structurally impossible through it; that only ever goes through a
    new revision row via `add_vintage`.

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
    # FX-43H.1: fails closed -- False (the default) marks a provisional
    # proxy (e.g. FX-43's backfill, which uses an effective-date proxy
    # for released_at); True means released_at/effective_at are confirmed
    # timestamps, and must be set explicitly by a caller that actually
    # has them. One of two columns a narrowly-scoped, atomic UPDATE is
    # ever issued against -- see
    # SqlAlchemyMacroObservationRepository.replace_provisional_release_timing.
    released_at_is_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    # FX-44: the other, narrower alternative outcome of that same atomic
    # UPDATE -- True marks released_at as a deliberately conservative,
    # research-safe bound (not the exact confirmed moment) rather than
    # an exact verified timestamp. Never both this and released_at_is_
    # verified True at once in practice (see the domain field's own
    # docstring); defaults False (provisional, same as released_at_is_
    # verified) so an unclassified row makes no timing claim at all.
    released_at_is_conservative_bound: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
