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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from forex_agent.infrastructure.db.base import Base
from forex_agent.infrastructure.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ForecastPerformanceSnapshotRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """FX-66: one immutable, append-only `domain.forecast_performance_
    snapshot.ForecastPerformanceSnapshot`. `(snapshot_key, revision_
    sequence)` is unique.

    Section 18's own "snapshot membership must be queryable for
    subsequent auditing, should not be the only representation of
    exact evidence membership when relational constraints are
    needed" is satisfied by the two CHILD tables, `ForecastPerformance
    SnapshotMemberRow`/`ForecastPerformanceSnapshotExclusionRow`
    (proper FK rows, one per member/exclusion) -- `confusion_counts`/
    `realized_class_distribution` remain `JSONB` here (this codebase's
    own established convention for a small, non-relationally-critical
    list-of-tuples diagnostic, mirroring `NewsSemanticAnnotationVintage
    Row`'s own precedent) since nothing ever needs to query INTO them
    independently of their own parent row. `excluded_by_reason` is
    NOT persisted at all -- fully reconstructable via `COUNT(*) GROUP
    BY reason` over the exclusions child table, never duplicated."""

    __tablename__ = "forecast_performance_snapshots"
    __table_args__ = (
        UniqueConstraint("snapshot_key", "revision_sequence", name="uq_fps_identity"),
        ForeignKeyConstraint(
            ["cohort_key", "cohort_version_sequence"],
            [
                "forecast_performance_cohorts.cohort_key",
                "forecast_performance_cohorts.version_sequence",
            ],
            name="fk_fps_cohort",
        ),
        ForeignKeyConstraint(
            ["methodology_key", "methodology_version_sequence"],
            [
                "forecast_performance_methodologies.methodology_key",
                "forecast_performance_methodologies.version_sequence",
            ],
            name="fk_fps_methodology",
        ),
        CheckConstraint("revision_sequence >= 0", name="ck_fps_revision_sequence"),
        CheckConstraint("cohort_version_sequence >= 0", name="ck_fps_cohort_version_sequence"),
        CheckConstraint(
            "methodology_version_sequence >= 0", name="ck_fps_methodology_version_sequence"
        ),
        CheckConstraint(
            "evaluation_mode IN ('PRODUCTION_OBSERVED', 'RETROSPECTIVE_RESEARCH')",
            name="ck_fps_evaluation_mode",
        ),
        CheckConstraint("algorithm_version <> ''", name="ck_fps_algorithm_version"),
        CheckConstraint(
            "(numeric_n IS NULL OR categorical_n IS NULL)", name="ck_fps_summary_exclusive"
        ),
        CheckConstraint(
            "benchmark_status IN ('COMPARED', 'BENCHMARK_UNAVAILABLE')",
            name="ck_fps_benchmark_status",
        ),
        CheckConstraint(
            "sample_adequacy IN "
            "('INSUFFICIENT_DATA', 'DESCRIPTIVE_ONLY', 'COMPARABLE_SAMPLE', 'INFERENCE_SUPPORTED')",
            name="ck_fps_sample_adequacy",
        ),
    )

    snapshot_key: Mapped[str] = mapped_column(String, nullable=False)
    revision_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    methodology_key: Mapped[str] = mapped_column(String, nullable=False)
    methodology_version_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    cohort_key: Mapped[str] = mapped_column(String, nullable=False)
    cohort_version_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    evaluation_mode: Mapped[str] = mapped_column(String, nullable=False)
    knowledge_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    availability: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String, nullable=False)

    numeric_n: Mapped[int | None] = mapped_column(Integer, nullable=True)
    numeric_unit: Mapped[str | None] = mapped_column(String, nullable=True)
    numeric_mean_absolute_error: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    numeric_mean_signed_error: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    numeric_root_mean_squared_error: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)

    categorical_n: Mapped[int | None] = mapped_column(Integer, nullable=True)
    categorical_match_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    categorical_mismatch_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    categorical_accuracy: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    confusion_counts: Mapped[list[list[object]] | None] = mapped_column(JSONB, nullable=True)
    realized_class_distribution: Mapped[list[list[object]] | None] = mapped_column(
        JSONB, nullable=True
    )

    benchmark_status: Mapped[str] = mapped_column(String, nullable=False)
    benchmark_key: Mapped[str | None] = mapped_column(String, nullable=True)
    benchmark_version_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    benchmark_paired_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_mean_absolute_error: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    benchmark_mean_absolute_error: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    mean_absolute_error_difference: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    relative_mae_improvement: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    source_accuracy: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    benchmark_accuracy: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    accuracy_difference: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)

    diag_raw_candidate_count: Mapped[int] = mapped_column(Integer, nullable=False)
    diag_accepted_count: Mapped[int] = mapped_column(Integer, nullable=False)
    diag_unique_forecast_issue_count: Mapped[int] = mapped_column(Integer, nullable=False)
    diag_unique_target_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    diag_distinct_target_period_count: Mapped[int] = mapped_column(Integer, nullable=False)
    diag_production_count: Mapped[int] = mapped_column(Integer, nullable=False)
    diag_research_count: Mapped[int] = mapped_column(Integer, nullable=False)
    diag_missing_outcome_rate: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    diag_earliest_availability: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    diag_latest_availability: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sample_adequacy: Mapped[str] = mapped_column(String, nullable=False)

    correction_reason: Mapped[str | None] = mapped_column(String, nullable=True)


class ForecastPerformanceSnapshotMemberRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """FX-66 Section 18: one accepted cohort member's own exact
    evidence reference -- a proper, independently queryable child
    row, mirroring Section 18's own explicit "relational constraints
    where needed" requirement."""

    __tablename__ = "forecast_performance_snapshot_members"
    __table_args__ = (
        ForeignKeyConstraint(
            ["snapshot_key", "snapshot_revision_sequence"],
            [
                "forecast_performance_snapshots.snapshot_key",
                "forecast_performance_snapshots.revision_sequence",
            ],
            name="fk_fpsm_snapshot",
        ),
        UniqueConstraint(
            "snapshot_key",
            "snapshot_revision_sequence",
            "evaluation_key",
            name="uq_fpsm_identity",
        ),
        CheckConstraint(
            "snapshot_revision_sequence >= 0", name="ck_fpsm_snapshot_revision_sequence"
        ),
        CheckConstraint("evaluation_revision_sequence >= 0", name="ck_fpsm_evaluation_revision"),
        CheckConstraint("forecast_revision_sequence >= 0", name="ck_fpsm_forecast_revision"),
        CheckConstraint("outcome_revision_sequence >= 0", name="ck_fpsm_outcome_revision"),
    )

    snapshot_key: Mapped[str] = mapped_column(String, nullable=False)
    snapshot_revision_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    evaluation_key: Mapped[str] = mapped_column(String, nullable=False)
    evaluation_revision_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    forecast_claim_key: Mapped[str] = mapped_column(String, nullable=False)
    forecast_revision_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome_key: Mapped[str] = mapped_column(String, nullable=False)
    outcome_revision_sequence: Mapped[int] = mapped_column(Integer, nullable=False)


class ForecastPerformanceSnapshotExclusionRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """FX-66 Section 6: one excluded candidate, with its own reason --
    the audit trail Section 6 requires, as a proper, independently
    queryable child row."""

    __tablename__ = "forecast_performance_snapshot_exclusions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["snapshot_key", "snapshot_revision_sequence"],
            [
                "forecast_performance_snapshots.snapshot_key",
                "forecast_performance_snapshots.revision_sequence",
            ],
            name="fk_fpse_snapshot",
        ),
        UniqueConstraint(
            "snapshot_key",
            "snapshot_revision_sequence",
            "evaluation_key",
            name="uq_fpse_identity",
        ),
        CheckConstraint(
            "snapshot_revision_sequence >= 0", name="ck_fpse_snapshot_revision_sequence"
        ),
    )

    snapshot_key: Mapped[str] = mapped_column(String, nullable=False)
    snapshot_revision_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    evaluation_key: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
