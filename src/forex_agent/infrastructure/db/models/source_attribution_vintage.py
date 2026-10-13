from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from forex_agent.infrastructure.db.base import Base
from forex_agent.infrastructure.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class SourceAttributionVintageRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One immutable, append-only FX-62 attribution vintage (`domain.
    source_attribution_vintage.SourceAttributionVintage`). No
    application code path ever UPDATEs an existing row -- a correction
    is INSERTED as a new row with a higher `revision_sequence` for the
    SAME `(news_item_key, role)` pair.

    `(news_item_key, role, revision_sequence)` is unique -- EACH role
    carries its own independent revision history. `news_item_key`
    carries a genuine `FOREIGN KEY` into `news_items` (FX-56/57's own
    table, read-only from FX-62's own perspective); `(news_item_key,
    evidence_basis_revision_sequence)` carries a genuine COMPOSITE
    `FOREIGN KEY` into `news_item_vintages`, mirroring `NewsSemantic
    AnnotationVintageRow.fk_nsav_basis_vintage` exactly. `attributed_
    source_key` is a NULLABLE `FOREIGN KEY` into `intelligence_sources`
    -- `NULL` precisely when `status = 'UNRESOLVED'` (enforced by
    `ck_sav_status_source_key_consistency` below, mirroring the
    domain-level invariant in storage too, the same discipline FX-60's
    own `ck_..._*` constraints already established for enum-like
    mutual-exclusivity)."""

    __tablename__ = "source_attribution_vintages"
    __table_args__ = (
        UniqueConstraint(
            "news_item_key",
            "role",
            "revision_sequence",
            name="uq_sav_identity",
        ),
        ForeignKeyConstraint(
            ["news_item_key"],
            ["news_items.news_item_key"],
            name="fk_sav_news_item",
        ),
        ForeignKeyConstraint(
            ["news_item_key", "evidence_basis_revision_sequence"],
            ["news_item_vintages.news_item_key", "news_item_vintages.revision_sequence"],
            name="fk_sav_basis_vintage",
        ),
        ForeignKeyConstraint(
            ["attributed_source_key"],
            ["intelligence_sources.source_key"],
            name="fk_sav_attributed_source",
        ),
        Index(
            "ix_sav_item_role_availability",
            "news_item_key",
            "role",
            "availability",
            "revision_sequence",
        ),
        CheckConstraint(
            "revision_sequence >= 0",
            name="ck_sav_revision_sequence",
        ),
        CheckConstraint(
            "evidence_basis_revision_sequence >= 0",
            name="ck_sav_evidence_basis_revision_sequence",
        ),
        CheckConstraint(
            "algorithm_version <> ''",
            name="ck_sav_algorithm_version",
        ),
        CheckConstraint(
            "role IN ('PUBLISHER', 'ORIGINATING_CLAIMANT', 'QUOTED_ACTOR')",
            name="ck_sav_role",
        ),
        CheckConstraint(
            "status IN ('CONFIRMED', 'UNRESOLVED')",
            name="ck_sav_status",
        ),
        CheckConstraint(
            "(status = 'CONFIRMED' AND attributed_source_key IS NOT NULL) OR "
            "(status = 'UNRESOLVED' AND attributed_source_key IS NULL)",
            name="ck_sav_status_source_key_consistency",
        ),
        CheckConstraint(
            "evidence_kind IN "
            "('ADAPTER_CONFIGURATION', 'SOURCE_NATIVE_METADATA', "
            "'AUTHORITATIVE_REFERENCE', 'MANUAL_REVIEW')",
            name="ck_sav_evidence_kind",
        ),
        CheckConstraint(
            "evidence_description <> ''",
            name="ck_sav_evidence_description",
        ),
        CheckConstraint(
            "corrects_revision_sequence IS NULL OR corrects_revision_sequence < revision_sequence",
            name="ck_sav_corrects_revision_sequence",
        ),
    )

    news_item_key: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    revision_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    availability: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    attributed_source_key: Mapped[str | None] = mapped_column(String, nullable=True)
    evidence_basis_revision_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_kind: Mapped[str] = mapped_column(String, nullable=False)
    evidence_description: Mapped[str] = mapped_column(String, nullable=False)
    corrects_revision_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
