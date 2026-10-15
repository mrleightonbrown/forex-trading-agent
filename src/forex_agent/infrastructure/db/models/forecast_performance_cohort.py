from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from forex_agent.infrastructure.db.base import Base
from forex_agent.infrastructure.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ForecastPerformanceCohortRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """FX-66: one append-only version of `domain.forecast_performance_
    cohort_definition.ForecastPerformanceCohortDefinition`. `(cohort_
    key, version_sequence)` is unique. `known_duplicate_evaluation_
    keys` is `JSONB` (this codebase's own established convention for a
    list-of-strings column, mirroring `SourceIdentityVintageRow.aliases`).
    No FK on `target_key` -- mirrors `ForecastOutcomeDefinitionRow`/
    `ForecastEvaluationProtocolRow`'s own precedent exactly (validated
    against the Python `forecast_target_registry` at construction
    time, never a DB table)."""

    __tablename__ = "forecast_performance_cohorts"
    __table_args__ = (
        UniqueConstraint("cohort_key", "version_sequence", name="uq_fpc_identity"),
        ForeignKeyConstraint(
            ["originator_publisher_source_key"],
            ["intelligence_sources.source_key"],
            name="fk_fpc_originator_publisher",
        ),
        ForeignKeyConstraint(
            ["originator_forecaster_source_key"],
            ["intelligence_sources.source_key"],
            name="fk_fpc_originator_forecaster",
        ),
        ForeignKeyConstraint(
            ["protocol_key", "protocol_version_sequence"],
            [
                "forecast_evaluation_protocols.protocol_key",
                "forecast_evaluation_protocols.version_sequence",
            ],
            name="fk_fpc_protocol",
        ),
        CheckConstraint("version_sequence >= 0", name="ck_fpc_version_sequence"),
        CheckConstraint(
            "attribution_kind IN "
            "('NAMED_INSTITUTION', 'AGGREGATE_SURVEY_CONSENSUS', 'ANONYMOUS_RESPONDENT')",
            name="ck_fpc_attribution_kind",
        ),
        CheckConstraint(
            "(attribution_kind = 'NAMED_INSTITUTION' AND originator_forecaster_source_key IS "
            "NOT NULL) OR "
            "(attribution_kind <> 'NAMED_INSTITUTION' AND originator_forecaster_source_key IS "
            "NULL)",
            name="ck_fpc_originator_shape",
        ),
        CheckConstraint("target_key <> ''", name="ck_fpc_target_key"),
        CheckConstraint(
            "forecast_type IN ('NUMERIC_POINT', 'CATEGORICAL_EVENT')", name="ck_fpc_forecast_type"
        ),
        CheckConstraint("horizon_category <> ''", name="ck_fpc_horizon_category"),
        CheckConstraint("protocol_key <> ''", name="ck_fpc_protocol_key"),
        CheckConstraint("protocol_version_sequence >= 0", name="ck_fpc_protocol_version_sequence"),
        CheckConstraint(
            "evaluation_mode IN ('PRODUCTION_OBSERVED', 'RETROSPECTIVE_RESEARCH')",
            name="ck_fpc_evaluation_mode",
        ),
        CheckConstraint(
            "duplicate_selection_policy IN ('EARLIEST_QUALIFYING_ISSUE')",
            name="ck_fpc_duplicate_selection_policy",
        ),
        CheckConstraint("rationale <> ''", name="ck_fpc_rationale"),
    )

    cohort_key: Mapped[str] = mapped_column(String, nullable=False)
    version_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    attribution_kind: Mapped[str] = mapped_column(String, nullable=False)
    originator_publisher_source_key: Mapped[str] = mapped_column(String, nullable=False)
    originator_forecaster_source_key: Mapped[str | None] = mapped_column(String, nullable=True)
    target_key: Mapped[str] = mapped_column(String, nullable=False)
    forecast_type: Mapped[str] = mapped_column(String, nullable=False)
    horizon_category: Mapped[str] = mapped_column(String, nullable=False)
    protocol_key: Mapped[str] = mapped_column(String, nullable=False)
    protocol_version_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    evaluation_mode: Mapped[str] = mapped_column(String, nullable=False)
    duplicate_selection_policy: Mapped[str] = mapped_column(String, nullable=False)
    issue_window_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    issue_window_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    known_duplicate_evaluation_keys: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    availability: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rationale: Mapped[str] = mapped_column(String, nullable=False)
    correction_reason: Mapped[str | None] = mapped_column(String, nullable=True)
