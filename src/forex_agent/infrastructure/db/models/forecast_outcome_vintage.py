from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from forex_agent.infrastructure.db.base import Base
from forex_agent.infrastructure.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ForecastOutcomeVintageRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """FX-65: one immutable, append-only outcome observation
    (`domain.forecast_outcome_vintage.ForecastOutcomeVintage`). Every
    value object (`ForecastTargetPeriod`/`ForecastEvidenceReference`/
    `EvidenceAuthenticationReview`) is flattened directly onto this ONE
    row, mirroring FX-62/64's own flattening convention.

    `(outcome_key, revision_sequence)` is unique. `(definition_key,
    definition_version_sequence)` carries a composite FK onto
    `forecast_outcome_definitions`, pinning the EXACT definition
    version this observation was captured under. `(news_item_key,
    basis_revision_sequence)` mirrors FX-59/62/64's own composite
    basis-pinning FK, auto-skipped when either column is NULL."""

    __tablename__ = "forecast_outcome_vintages"
    __table_args__ = (
        UniqueConstraint("outcome_key", "revision_sequence", name="uq_outcome_vintage_identity"),
        ForeignKeyConstraint(
            ["definition_key", "definition_version_sequence"],
            [
                "forecast_outcome_definitions.definition_key",
                "forecast_outcome_definitions.version_sequence",
            ],
            name="fk_outcome_vintage_definition",
        ),
        ForeignKeyConstraint(
            ["news_item_key", "basis_revision_sequence"],
            ["news_item_vintages.news_item_key", "news_item_vintages.revision_sequence"],
            name="fk_outcome_vintage_basis",
        ),
        CheckConstraint("revision_sequence >= 0", name="ck_outcome_vintage_revision_sequence"),
        CheckConstraint("outcome_key <> ''", name="ck_outcome_vintage_key"),
        CheckConstraint(
            "outcome_type IN ('NUMERIC_POINT', 'CATEGORICAL_EVENT')",
            name="ck_outcome_vintage_type",
        ),
        CheckConstraint(
            "(outcome_type = 'NUMERIC_POINT' AND numeric_value IS NOT NULL AND unit IS NOT "
            "NULL AND categorical_outcome IS NULL) OR "
            "(outcome_type = 'CATEGORICAL_EVENT' AND categorical_outcome IS NOT NULL AND "
            "numeric_value IS NULL AND unit IS NULL)",
            name="ck_outcome_vintage_payload_shape",
        ),
        CheckConstraint(
            "target_period_kind IN "
            "('CALENDAR_YEAR', 'CALENDAR_QUARTER', 'CALENDAR_MONTH', 'SPECIFIC_DATE', "
            "'POLICY_MEETING')",
            name="ck_outcome_vintage_period_kind",
        ),
        CheckConstraint(
            "evidence_kind IN ('NEWS_ITEM_VINTAGE_BASIS', 'EXTERNAL_DOCUMENT_REFERENCE')",
            name="ck_outcome_vintage_evidence_kind",
        ),
        CheckConstraint(
            "evidence_description <> ''", name="ck_outcome_vintage_evidence_description"
        ),
        CheckConstraint(
            "(evidence_kind = 'NEWS_ITEM_VINTAGE_BASIS' AND news_item_key IS NOT NULL AND "
            "basis_revision_sequence IS NOT NULL AND document_identifier IS NULL) OR "
            "(evidence_kind = 'EXTERNAL_DOCUMENT_REFERENCE' AND document_identifier IS NOT "
            "NULL AND news_item_key IS NULL AND basis_revision_sequence IS NULL)",
            name="ck_outcome_vintage_evidence_shape",
        ),
        CheckConstraint(
            "provenance_mode IN ('PRODUCTION_OBSERVED', 'RETROSPECTIVE_RESEARCH')",
            name="ck_outcome_vintage_provenance_mode",
        ),
        CheckConstraint("reviewed_by <> ''", name="ck_outcome_vintage_reviewed_by"),
        CheckConstraint("review_method <> ''", name="ck_outcome_vintage_review_method"),
    )

    outcome_key: Mapped[str] = mapped_column(String, nullable=False)
    revision_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    definition_key: Mapped[str] = mapped_column(String, nullable=False)
    definition_version_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    availability: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    target_period_kind: Mapped[str] = mapped_column(String, nullable=False)
    calendar_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    calendar_quarter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    calendar_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    specific_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    policy_meeting_identifier: Mapped[str | None] = mapped_column(String, nullable=True)
    outcome_type: Mapped[str] = mapped_column(String, nullable=False)
    numeric_value: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    unit: Mapped[str | None] = mapped_column(String, nullable=True)
    categorical_outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    evidence_kind: Mapped[str] = mapped_column(String, nullable=False)
    evidence_description: Mapped[str] = mapped_column(String, nullable=False)
    news_item_key: Mapped[str | None] = mapped_column(String, nullable=True)
    basis_revision_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    document_identifier: Mapped[str | None] = mapped_column(String, nullable=True)
    document_locator: Mapped[str | None] = mapped_column(String, nullable=True)
    official_reference_url: Mapped[str | None] = mapped_column(String, nullable=True)
    content_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    publisher_declared_publication_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewed_by: Mapped[str] = mapped_column(String, nullable=False)
    review_method: Mapped[str] = mapped_column(String, nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    corroboration_reference: Mapped[str | None] = mapped_column(String, nullable=True)
    provenance_mode: Mapped[str] = mapped_column(String, nullable=False)
    provider_release_identifier: Mapped[str | None] = mapped_column(String, nullable=True)
    provider_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    content_integrity_reference: Mapped[str | None] = mapped_column(String, nullable=True)
    correction_reason: Mapped[str | None] = mapped_column(String, nullable=True)
