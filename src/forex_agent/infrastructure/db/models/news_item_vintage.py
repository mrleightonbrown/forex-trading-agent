from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from forex_agent.infrastructure.db.base import Base
from forex_agent.infrastructure.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class NewsItemVintageRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One immutable point-in-time-safe news fact (FX-56). A content
    change, withdrawal, or quarantine-status change is INSERTED as a
    new row with a higher `revision_sequence` -- this table has no
    application code path that UPDATEs an existing row.

    `(news_item_key, revision_sequence)` is unique -- the natural
    identity of one vintage (matching `EconomicEventScheduleVintageRow`'s
    own shape). `news_item_key` carries a genuine `FOREIGN KEY` into
    `news_items`.

    `ck_..._quarantine_reason` mirrors the domain layer's own
    quarantine-reason mutual-exclusivity check (`domain.
    news_item_vintage.NewsItemVintage.__post_init__`) in storage, so
    the invariant holds even for a row written by a future path that
    bypasses the domain constructor. `ck_..._revision_sequence`/
    `ck_..._observation_mode`/`ck_..._source_status`/`ck_..._
    evidence_disposition` (FX-56H) mirror the remaining domain
    `__post_init__` checks and the enum members themselves the same
    way -- added by a follow-up migration, not by editing the
    already-deployed table-creation migration in place.

    `source_channel` (FX-57B, migration `a95058f88727`) is `NOT NULL`
    -- every row written since that migration supplies a real channel
    value; the migration backfilled every pre-existing (Fed-only) row
    deterministically from its own `source_content_type` before
    adding the constraint.

    `authors`/`source_timestamp_provenance`/`source_revision_metadata`
    are `JSONB` -- this project's first use of semi-structured
    persistence (no existing JSONB convention to reuse; see this
    story's own `docs/DECISIONS.md` entry). Each is validated on
    load/write by `SqlAlchemyNewsRepository`'s own serialization
    helpers, which reconstruct validating domain objects rather than
    trusting the stored shape -- a malformed stored structure fails
    loudly there, not silently here. `source_timestamp_provenance`/
    `source_revision_metadata` default to an empty list, never `NULL`,
    so a read never needs to distinguish "no provenance" from
    "missing column."
    """

    __tablename__ = "news_item_vintages"
    __table_args__ = (
        UniqueConstraint(
            "news_item_key",
            "revision_sequence",
            name="uq_news_item_vintages_identity",
        ),
        ForeignKeyConstraint(
            ["news_item_key"],
            ["news_items.news_item_key"],
            name="fk_news_item_vintages_news_item",
        ),
        Index(
            "ix_news_item_vintages_item_availability",
            "news_item_key",
            "availability",
        ),
        CheckConstraint(
            "(evidence_disposition = 'QUARANTINED') = (quarantine_reason IS NOT NULL)",
            name="ck_news_item_vintages_quarantine_reason",
        ),
        CheckConstraint(
            "revision_sequence >= 0",
            name="ck_news_item_vintages_revision_sequence",
        ),
        CheckConstraint(
            "observation_mode IN ('PROSPECTIVE', 'BACKFILL')",
            name="ck_news_item_vintages_observation_mode",
        ),
        CheckConstraint(
            "source_status IN ('ACTIVE', 'WITHDRAWN')",
            name="ck_news_item_vintages_source_status",
        ),
        CheckConstraint(
            "evidence_disposition IN ('EVIDENCE_ELIGIBLE', 'QUARANTINED')",
            name="ck_news_item_vintages_evidence_disposition",
        ),
    )

    news_item_key: Mapped[str] = mapped_column(String, nullable=False)
    revision_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    availability: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observation_mode: Mapped[str] = mapped_column(String, nullable=False)
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    source_channel: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonical_url: Mapped[str | None] = mapped_column(String, nullable=True)
    authors: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    language: Mapped[str | None] = mapped_column(String, nullable=True)
    source_content_type: Mapped[str | None] = mapped_column(String, nullable=True)
    source_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_timestamp_provenance: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    source_revision_metadata: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    source_status: Mapped[str] = mapped_column(String, nullable=False)
    evidence_disposition: Mapped[str] = mapped_column(String, nullable=False)
    quarantine_reason: Mapped[str | None] = mapped_column(String, nullable=True)
