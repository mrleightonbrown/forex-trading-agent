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


class ForecastOutcomeDefinitionRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """FX-65: one append-only version of an outcome definition
    (`domain.forecast_outcome_definition.ForecastOutcomeDefinition`).
    `(definition_key, version_sequence)` is unique -- no separate
    identity table, mirroring `macro_observation_vintages`'s own
    simpler single-table-per-concept precedent rather than FX-62/64's
    claim+vintage split (this concept needs no `registered_at`
    distinct from version 0's own `availability`).

    `provider_source_key` carries a genuine FK into `intelligence_
    sources` (FX-62 reuse); `target_key` is NOT a database FK (FX-64's
    `forecast_target_registry` is a code-level registry, not a table)
    -- cross-validated instead by the domain type's own `__post_
    init__`."""

    __tablename__ = "forecast_outcome_definitions"
    __table_args__ = (
        UniqueConstraint(
            "definition_key", "version_sequence", name="uq_outcome_definition_identity"
        ),
        ForeignKeyConstraint(
            ["provider_source_key"],
            ["intelligence_sources.source_key"],
            name="fk_outcome_definition_provider_source",
        ),
        CheckConstraint("version_sequence >= 0", name="ck_outcome_definition_version_sequence"),
        CheckConstraint("definition_key <> ''", name="ck_outcome_definition_key"),
        CheckConstraint("target_key <> ''", name="ck_outcome_definition_target_key"),
        CheckConstraint(
            "outcome_type IN ('NUMERIC_POINT', 'CATEGORICAL_EVENT')",
            name="ck_outcome_definition_outcome_type",
        ),
        CheckConstraint(
            "outcome_vintage_selection_policy IN "
            "('FIRST_RELEASE', 'LATEST_AVAILABLE_AS_OF', 'FIXED_RELEASE_VINTAGE')",
            name="ck_outcome_definition_selection_policy",
        ),
        CheckConstraint(
            "required_source_series_identifier <> ''",
            name="ck_outcome_definition_series_identifier",
        ),
        CheckConstraint(
            "supporting_definition_reference <> ''",
            name="ck_outcome_definition_supporting_reference",
        ),
    )

    definition_key: Mapped[str] = mapped_column(String, nullable=False)
    version_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    target_key: Mapped[str] = mapped_column(String, nullable=False)
    outcome_type: Mapped[str] = mapped_column(String, nullable=False)
    provider_source_key: Mapped[str] = mapped_column(String, nullable=False)
    required_source_series_identifier: Mapped[str] = mapped_column(String, nullable=False)
    outcome_vintage_selection_policy: Mapped[str] = mapped_column(String, nullable=False)
    availability: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    supporting_definition_reference: Mapped[str] = mapped_column(String, nullable=False)
    correction_reason: Mapped[str | None] = mapped_column(String, nullable=True)
