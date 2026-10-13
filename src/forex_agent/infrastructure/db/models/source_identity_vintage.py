from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from forex_agent.infrastructure.db.base import Base
from forex_agent.infrastructure.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class SourceIdentityVintageRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One immutable, append-only FX-62 identity vintage (`domain.
    source_identity_vintage.SourceIdentityVintage`). This table has no
    application code path that UPDATEs an existing row -- a correction
    or a genuine real-world change is INSERTED as a new row with a
    higher `revision_sequence`, mirroring `NewsSemanticAnnotationVintage
    Row`'s own append-only shape exactly.

    `(source_key, revision_sequence)` is unique; `source_key` carries a
    genuine `FOREIGN KEY` into `intelligence_sources`. `aliases` is a
    `JSONB` array of strings (FX-56's own semi-structured-persistence
    precedent), validated on load/write by `SqlAlchemySourceRegistry
    Repository`'s own serialization helpers."""

    __tablename__ = "source_identity_vintages"
    __table_args__ = (
        UniqueConstraint(
            "source_key",
            "revision_sequence",
            name="uq_siv_identity",
        ),
        ForeignKeyConstraint(
            ["source_key"],
            ["intelligence_sources.source_key"],
            name="fk_siv_source",
        ),
        Index(
            "ix_siv_source_availability",
            "source_key",
            "availability",
            "revision_sequence",
        ),
        CheckConstraint(
            "revision_sequence >= 0",
            name="ck_siv_revision_sequence",
        ),
        CheckConstraint(
            "algorithm_version <> ''",
            name="ck_siv_algorithm_version",
        ),
        CheckConstraint(
            "display_name <> ''",
            name="ck_siv_display_name",
        ),
        CheckConstraint(
            "jsonb_typeof(aliases) = 'array'",
            name="ck_siv_aliases_array",
        ),
        CheckConstraint(
            "evidence_kind IN "
            "('ADAPTER_CONFIGURATION', 'SOURCE_NATIVE_METADATA', "
            "'AUTHORITATIVE_REFERENCE', 'MANUAL_REVIEW')",
            name="ck_siv_evidence_kind",
        ),
        CheckConstraint(
            "evidence_description <> ''",
            name="ck_siv_evidence_description",
        ),
    )

    source_key: Mapped[str] = mapped_column(String, nullable=False)
    revision_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    availability: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    aliases: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    authoritative_identifier: Mapped[str | None] = mapped_column(String, nullable=True)
    canonical_website: Mapped[str | None] = mapped_column(String, nullable=True)
    evidence_kind: Mapped[str] = mapped_column(String, nullable=False)
    evidence_description: Mapped[str] = mapped_column(String, nullable=False)
    correction_reason: Mapped[str | None] = mapped_column(String, nullable=True)
