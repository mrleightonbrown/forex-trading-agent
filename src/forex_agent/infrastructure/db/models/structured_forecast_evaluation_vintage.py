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


class StructuredForecastEvaluationVintageRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """FX-65: one immutable, append-only evaluation vintage
    (`domain.structured_forecast_evaluation_vintage.Structured
    ForecastEvaluationVintage`). `(evaluation_key, revision_sequence)`
    is unique. Carries genuine composite FKs pinning the EXACT
    forecast claim vintage, protocol version, outcome definition
    version, and outcome vintage this evaluation used -- Section 11's
    own "exact basis" requirement enforced at the database layer, not
    merely by application-layer discipline.

    No FK is needed for `forecast_authentication_review` (flattened
    value object, not a reference)."""

    __tablename__ = "structured_forecast_evaluation_vintages"
    __table_args__ = (
        UniqueConstraint("evaluation_key", "revision_sequence", name="uq_evaluation_identity"),
        ForeignKeyConstraint(
            ["forecast_claim_key", "forecast_revision_sequence"],
            [
                "structured_forecast_vintages.claim_key",
                "structured_forecast_vintages.revision_sequence",
            ],
            name="fk_evaluation_forecast_vintage",
        ),
        ForeignKeyConstraint(
            ["protocol_key", "protocol_version_sequence"],
            [
                "forecast_evaluation_protocols.protocol_key",
                "forecast_evaluation_protocols.version_sequence",
            ],
            name="fk_evaluation_protocol_version",
        ),
        ForeignKeyConstraint(
            ["outcome_definition_key", "outcome_definition_version_sequence"],
            [
                "forecast_outcome_definitions.definition_key",
                "forecast_outcome_definitions.version_sequence",
            ],
            name="fk_evaluation_outcome_definition",
        ),
        ForeignKeyConstraint(
            ["outcome_key", "outcome_revision_sequence"],
            [
                "forecast_outcome_vintages.outcome_key",
                "forecast_outcome_vintages.revision_sequence",
            ],
            name="fk_evaluation_outcome_vintage",
        ),
        CheckConstraint("revision_sequence >= 0", name="ck_evaluation_revision_sequence"),
        CheckConstraint("evaluation_key <> ''", name="ck_evaluation_key"),
        CheckConstraint(
            "evaluation_mode IN ('PRODUCTION_OBSERVED', 'RETROSPECTIVE_RESEARCH')",
            name="ck_evaluation_mode",
        ),
        CheckConstraint("algorithm_version <> ''", name="ck_evaluation_algorithm_version"),
        CheckConstraint(
            "metric IN ('NUMERIC_ERROR', 'CATEGORICAL_MATCH')", name="ck_evaluation_metric"
        ),
        CheckConstraint(
            "(metric = 'NUMERIC_ERROR' AND signed_error IS NOT NULL AND absolute_error IS NOT "
            "NULL AND result_unit IS NOT NULL AND categorical_result IS NULL) OR "
            "(metric = 'CATEGORICAL_MATCH' AND categorical_result IS NOT NULL AND "
            "signed_error IS NULL AND absolute_error IS NULL AND result_unit IS NULL)",
            name="ck_evaluation_result_shape",
        ),
        CheckConstraint(
            "categorical_result IS NULL OR categorical_result IN ('MATCH', 'MISMATCH')",
            name="ck_evaluation_categorical_result",
        ),
        CheckConstraint("forecast_reviewed_by <> ''", name="ck_evaluation_reviewed_by"),
        CheckConstraint("forecast_review_method <> ''", name="ck_evaluation_review_method"),
    )

    evaluation_key: Mapped[str] = mapped_column(String, nullable=False)
    revision_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    forecast_claim_key: Mapped[str] = mapped_column(String, nullable=False)
    forecast_revision_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    protocol_key: Mapped[str] = mapped_column(String, nullable=False)
    protocol_version_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome_definition_key: Mapped[str] = mapped_column(String, nullable=False)
    outcome_definition_version_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome_key: Mapped[str] = mapped_column(String, nullable=False)
    outcome_revision_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    evaluation_mode: Mapped[str] = mapped_column(String, nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String, nullable=False)
    availability: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metric: Mapped[str] = mapped_column(String, nullable=False)
    signed_error: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    absolute_error: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    result_unit: Mapped[str | None] = mapped_column(String, nullable=True)
    categorical_result: Mapped[str | None] = mapped_column(String, nullable=True)
    forecast_reviewed_by: Mapped[str] = mapped_column(String, nullable=False)
    forecast_review_method: Mapped[str] = mapped_column(String, nullable=False)
    forecast_reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    forecast_corroboration_reference: Mapped[str | None] = mapped_column(String, nullable=True)
    correction_reason: Mapped[str | None] = mapped_column(String, nullable=True)
