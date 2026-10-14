from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from forex_agent.infrastructure.db.base import Base
from forex_agent.infrastructure.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ForecastEvaluationProtocolRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """FX-65: one append-only version of an evaluation protocol
    (`domain.forecast_evaluation_protocol.ForecastEvaluationProtocol`).
    `(protocol_key, version_sequence)` is unique. `(outcome_definition_
    key, outcome_definition_version_sequence)` carries a composite FK
    onto `forecast_outcome_definitions`, pinning the exact definition
    version this protocol evaluates against."""

    __tablename__ = "forecast_evaluation_protocols"
    __table_args__ = (
        UniqueConstraint(
            "protocol_key", "version_sequence", name="uq_evaluation_protocol_identity"
        ),
        ForeignKeyConstraint(
            ["outcome_definition_key", "outcome_definition_version_sequence"],
            [
                "forecast_outcome_definitions.definition_key",
                "forecast_outcome_definitions.version_sequence",
            ],
            name="fk_evaluation_protocol_outcome_definition",
        ),
        CheckConstraint("version_sequence >= 0", name="ck_evaluation_protocol_version_sequence"),
        CheckConstraint("protocol_key <> ''", name="ck_evaluation_protocol_key"),
        CheckConstraint(
            "supported_forecast_type IN ('NUMERIC_POINT', 'CATEGORICAL_EVENT')",
            name="ck_evaluation_protocol_forecast_type",
        ),
        CheckConstraint("target_key <> ''", name="ck_evaluation_protocol_target_key"),
        CheckConstraint(
            "outcome_definition_key <> ''", name="ck_evaluation_protocol_outcome_definition_key"
        ),
        CheckConstraint(
            "outcome_definition_version_sequence >= 0",
            name="ck_evaluation_protocol_outcome_definition_version",
        ),
        CheckConstraint(
            "outcome_vintage_selection_policy IN "
            "('FIRST_RELEASE', 'LATEST_AVAILABLE_AS_OF', 'FIXED_RELEASE_VINTAGE')",
            name="ck_evaluation_protocol_selection_policy",
        ),
        CheckConstraint(
            "metric IN ('NUMERIC_ERROR', 'CATEGORICAL_MATCH')", name="ck_evaluation_protocol_metric"
        ),
        CheckConstraint(
            "(outcome_vintage_selection_policy = 'FIXED_RELEASE_VINTAGE' AND "
            "fixed_outcome_revision_sequence IS NOT NULL) OR "
            "(outcome_vintage_selection_policy <> 'FIXED_RELEASE_VINTAGE' AND "
            "fixed_outcome_revision_sequence IS NULL)",
            name="ck_evaluation_protocol_fixed_revision_shape",
        ),
        CheckConstraint("rationale <> ''", name="ck_evaluation_protocol_rationale"),
    )

    protocol_key: Mapped[str] = mapped_column(String, nullable=False)
    version_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    supported_forecast_type: Mapped[str] = mapped_column(String, nullable=False)
    target_key: Mapped[str] = mapped_column(String, nullable=False)
    outcome_definition_key: Mapped[str] = mapped_column(String, nullable=False)
    outcome_definition_version_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome_vintage_selection_policy: Mapped[str] = mapped_column(String, nullable=False)
    fixed_outcome_revision_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metric: Mapped[str] = mapped_column(String, nullable=False)
    availability: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rationale: Mapped[str] = mapped_column(String, nullable=False)
    correction_reason: Mapped[str | None] = mapped_column(String, nullable=True)
