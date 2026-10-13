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


class StructuredForecastVintageRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """FX-64: one immutable, append-only structured-forecast vintage
    (`domain.structured_forecast_vintage.StructuredForecastVintage`).
    Every FX-64 value object (`ForecastTargetPeriod`/`ForecastAttribution`/
    `ForecastEvidenceReference`) is flattened directly onto this ONE
    row, mirroring FX-62's own `SourceIdentityVintageRow`/`SourceAttribution
    VintageRow` flattening convention exactly -- no separate tables for
    these value objects.

    `(claim_key, revision_sequence)` is unique; `claim_key` carries a
    genuine FK into `forecast_claims`. `publisher_source_key` carries a
    genuine, REQUIRED FK into `intelligence_sources` (FX-62 reuse,
    Section 8); `forecaster_source_key` is the SAME FK, but nullable
    (never populated for `AGGREGATE_SURVEY_CONSENSUS`/`ANONYMOUS_
    RESPONDENT`). `(news_item_key, basis_revision_sequence)` carries a
    composite FK into `news_item_vintages`, mirroring FX-59/62's own
    basis-pinning convention exactly -- automatically satisfied
    (skipped) by Postgres whenever either column is `NULL` (the
    `EXTERNAL_DOCUMENT_REFERENCE` evidence case)."""

    __tablename__ = "structured_forecast_vintages"
    __table_args__ = (
        UniqueConstraint("claim_key", "revision_sequence", name="uq_sfv_identity"),
        ForeignKeyConstraint(
            ["claim_key"],
            ["forecast_claims.claim_key"],
            name="fk_sfv_claim",
        ),
        ForeignKeyConstraint(
            ["publisher_source_key"],
            ["intelligence_sources.source_key"],
            name="fk_sfv_publisher_source",
        ),
        ForeignKeyConstraint(
            ["forecaster_source_key"],
            ["intelligence_sources.source_key"],
            name="fk_sfv_forecaster_source",
        ),
        ForeignKeyConstraint(
            ["news_item_key", "basis_revision_sequence"],
            ["news_item_vintages.news_item_key", "news_item_vintages.revision_sequence"],
            name="fk_sfv_basis_vintage",
        ),
        Index(
            "ix_sfv_claim_availability",
            "claim_key",
            "availability",
            "revision_sequence",
        ),
        Index(
            "ix_sfv_target_availability",
            "target_key",
            "availability",
        ),
        CheckConstraint("revision_sequence >= 0", name="ck_sfv_revision_sequence"),
        CheckConstraint("algorithm_version <> ''", name="ck_sfv_algorithm_version"),
        CheckConstraint("target_key <> ''", name="ck_sfv_target_key"),
        CheckConstraint(
            "forecast_type IN ('NUMERIC_POINT', 'CATEGORICAL_EVENT')",
            name="ck_sfv_forecast_type",
        ),
        CheckConstraint(
            "(forecast_type = 'NUMERIC_POINT' AND numeric_value IS NOT NULL AND unit IS NOT "
            "NULL AND categorical_outcome IS NULL) OR "
            "(forecast_type = 'CATEGORICAL_EVENT' AND categorical_outcome IS NOT NULL AND "
            "numeric_value IS NULL AND unit IS NULL)",
            name="ck_sfv_payload_shape",
        ),
        CheckConstraint(
            "target_period_kind IN "
            "('CALENDAR_YEAR', 'CALENDAR_QUARTER', 'CALENDAR_MONTH', 'SPECIFIC_DATE', "
            "'POLICY_MEETING')",
            name="ck_sfv_target_period_kind",
        ),
        CheckConstraint(
            "attribution_kind IN "
            "('NAMED_INSTITUTION', 'AGGREGATE_SURVEY_CONSENSUS', 'ANONYMOUS_RESPONDENT')",
            name="ck_sfv_attribution_kind",
        ),
        CheckConstraint(
            "(attribution_kind = 'NAMED_INSTITUTION' AND forecaster_source_key IS NOT NULL "
            "AND anonymous_respondent_id IS NULL) OR "
            "(attribution_kind = 'AGGREGATE_SURVEY_CONSENSUS' AND forecaster_source_key IS "
            "NULL AND anonymous_respondent_id IS NULL) OR "
            "(attribution_kind = 'ANONYMOUS_RESPONDENT' AND forecaster_source_key IS NULL)",
            name="ck_sfv_attribution_shape",
        ),
        CheckConstraint("publisher_source_key <> ''", name="ck_sfv_publisher_source_key"),
        CheckConstraint(
            "evidence_kind IN ('NEWS_ITEM_VINTAGE_BASIS', 'EXTERNAL_DOCUMENT_REFERENCE')",
            name="ck_sfv_evidence_kind",
        ),
        CheckConstraint("evidence_description <> ''", name="ck_sfv_evidence_description"),
        CheckConstraint(
            "(evidence_kind = 'NEWS_ITEM_VINTAGE_BASIS' AND news_item_key IS NOT NULL AND "
            "basis_revision_sequence IS NOT NULL AND document_identifier IS NULL) OR "
            "(evidence_kind = 'EXTERNAL_DOCUMENT_REFERENCE' AND document_identifier IS NOT "
            "NULL AND news_item_key IS NULL AND basis_revision_sequence IS NULL)",
            name="ck_sfv_evidence_shape",
        ),
    )

    claim_key: Mapped[str] = mapped_column(String, nullable=False)
    revision_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    availability: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String, nullable=False)
    forecast_type: Mapped[str] = mapped_column(String, nullable=False)
    target_key: Mapped[str] = mapped_column(String, nullable=False)
    target_period_kind: Mapped[str] = mapped_column(String, nullable=False)
    calendar_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    calendar_quarter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    calendar_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    specific_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    policy_meeting_identifier: Mapped[str | None] = mapped_column(String, nullable=True)
    numeric_value: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    unit: Mapped[str | None] = mapped_column(String, nullable=True)
    categorical_outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    attribution_kind: Mapped[str] = mapped_column(String, nullable=False)
    publisher_source_key: Mapped[str] = mapped_column(String, nullable=False)
    forecaster_source_key: Mapped[str | None] = mapped_column(String, nullable=True)
    anonymous_respondent_id: Mapped[str | None] = mapped_column(String, nullable=True)
    provenance_mode: Mapped[str] = mapped_column(String, nullable=False)
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
    original_publication_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    correction_reason: Mapped[str | None] = mapped_column(String, nullable=True)
