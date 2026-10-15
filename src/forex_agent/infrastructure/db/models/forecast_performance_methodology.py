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


class ForecastPerformanceMethodologyRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """FX-66: one append-only version of `domain.forecast_performance_
    methodology.ForecastPerformanceMethodology`. `(methodology_key,
    version_sequence)` is unique."""

    __tablename__ = "forecast_performance_methodologies"
    __table_args__ = (
        UniqueConstraint("methodology_key", "version_sequence", name="uq_fpm_identity"),
        ForeignKeyConstraint(
            ["cohort_key", "cohort_version_sequence"],
            [
                "forecast_performance_cohorts.cohort_key",
                "forecast_performance_cohorts.version_sequence",
            ],
            name="fk_fpm_cohort",
        ),
        ForeignKeyConstraint(
            ["benchmark_key", "benchmark_version_sequence"],
            [
                "forecast_performance_benchmarks.benchmark_key",
                "forecast_performance_benchmarks.version_sequence",
            ],
            name="fk_fpm_benchmark",
        ),
        CheckConstraint("version_sequence >= 0", name="ck_fpm_version_sequence"),
        CheckConstraint("cohort_version_sequence >= 0", name="ck_fpm_cohort_version_sequence"),
        CheckConstraint(
            "missing_data_policy IN ('EXCLUDE_FROM_DENOMINATOR')",
            name="ck_fpm_missing_data_policy",
        ),
        CheckConstraint("algorithm_version <> ''", name="ck_fpm_algorithm_version"),
        CheckConstraint("rationale <> ''", name="ck_fpm_rationale"),
        CheckConstraint(
            "(benchmark_key IS NULL AND benchmark_version_sequence IS NULL) OR "
            "(benchmark_key IS NOT NULL AND benchmark_version_sequence IS NOT NULL)",
            name="ck_fpm_benchmark_shape",
        ),
    )

    methodology_key: Mapped[str] = mapped_column(String, nullable=False)
    version_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    cohort_key: Mapped[str] = mapped_column(String, nullable=False)
    cohort_version_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    missing_data_policy: Mapped[str] = mapped_column(String, nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String, nullable=False)
    availability: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rationale: Mapped[str] = mapped_column(String, nullable=False)
    benchmark_key: Mapped[str | None] = mapped_column(String, nullable=True)
    benchmark_version_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    correction_reason: Mapped[str | None] = mapped_column(String, nullable=True)
