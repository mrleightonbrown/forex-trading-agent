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


class ForecastPerformanceBenchmarkRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """FX-66: one append-only version of `domain.forecast_performance_
    benchmark_definition.ForecastPerformanceBenchmarkDefinition`.
    `(benchmark_key, version_sequence)` is unique."""

    __tablename__ = "forecast_performance_benchmarks"
    __table_args__ = (
        UniqueConstraint("benchmark_key", "version_sequence", name="uq_fpb_identity"),
        ForeignKeyConstraint(
            ["benchmark_cohort_key", "benchmark_cohort_version_sequence"],
            [
                "forecast_performance_cohorts.cohort_key",
                "forecast_performance_cohorts.version_sequence",
            ],
            name="fk_fpb_benchmark_cohort",
        ),
        CheckConstraint("version_sequence >= 0", name="ck_fpb_version_sequence"),
        CheckConstraint(
            "kind IN ('AUTHENTICATED_SERIES', 'NAIVE_CATEGORICAL', 'NAIVE_NUMERIC')",
            name="ck_fpb_kind",
        ),
        CheckConstraint("target_key <> ''", name="ck_fpb_target_key"),
        CheckConstraint("horizon_category <> ''", name="ck_fpb_horizon_category"),
        CheckConstraint("metric IN ('NUMERIC_ERROR', 'CATEGORICAL_MATCH')", name="ck_fpb_metric"),
        CheckConstraint("rationale <> ''", name="ck_fpb_rationale"),
        CheckConstraint(
            "(kind = 'AUTHENTICATED_SERIES' AND benchmark_cohort_key IS NOT NULL AND "
            "benchmark_cohort_version_sequence IS NOT NULL AND naive_categorical_class IS NULL "
            "AND naive_numeric_reference_value IS NULL) OR "
            "(kind = 'NAIVE_CATEGORICAL' AND naive_categorical_class IS NOT NULL AND "
            "benchmark_cohort_key IS NULL AND naive_numeric_reference_value IS NULL) OR "
            "(kind = 'NAIVE_NUMERIC' AND naive_numeric_reference_value IS NOT NULL AND "
            "naive_numeric_reference_description IS NOT NULL AND benchmark_cohort_key IS NULL "
            "AND naive_categorical_class IS NULL)",
            name="ck_fpb_kind_shape",
        ),
    )

    benchmark_key: Mapped[str] = mapped_column(String, nullable=False)
    version_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    target_key: Mapped[str] = mapped_column(String, nullable=False)
    horizon_category: Mapped[str] = mapped_column(String, nullable=False)
    metric: Mapped[str] = mapped_column(String, nullable=False)
    availability: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rationale: Mapped[str] = mapped_column(String, nullable=False)
    benchmark_cohort_key: Mapped[str | None] = mapped_column(String, nullable=True)
    benchmark_cohort_version_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    naive_categorical_class: Mapped[str | None] = mapped_column(String, nullable=True)
    naive_numeric_reference_value: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    naive_numeric_reference_description: Mapped[str | None] = mapped_column(String, nullable=True)
    correction_reason: Mapped[str | None] = mapped_column(String, nullable=True)
