"""add forecast performance tables

FX-66: six new tables giving FTA a point-in-time-safe historical
FORECAST-PERFORMANCE measurement registry, layered strictly on top of
FX-62/64/65's own already-durable identity/attribution, structured-
forecast, outcome, and evaluation registries -- NONE of which are
touched, mutated, or gain a new column by this migration:

- `forecast_performance_cohorts` -- append-only cohort-definition
  versions (WHICH population of evaluations is genuinely comparable),
  single-table-per-concept (mirroring `forecast_outcome_definitions`'s
  own simpler precedent).
- `forecast_performance_benchmarks` -- append-only benchmark-
  definition versions.
- `forecast_performance_methodologies` -- append-only methodology
  versions (HOW a pinned cohort's own population is calculated).
- `forecast_performance_snapshots` -- immutable, append-only
  performance calculations, with genuine composite foreign keys
  pinning the EXACT cohort and methodology version each snapshot used.
- `forecast_performance_snapshot_members`/`forecast_performance_
  snapshot_exclusions` -- proper relational child tables for a
  snapshot's own EXACT accepted membership and excluded-candidate
  audit trail (Section 18's own "should not be the only
  representation of exact evidence membership when relational
  constraints are needed" requirement).

Downgrade is GUARDED from the start, mirroring every prior FX-56+
migration's own precedent exactly.

Revision ID: 0db892e6639a
Revises: 3b03a0c4f0ba
Create Date: 2026-10-15 00:00:00.000000

"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0db892e6639a"
down_revision: str | None = "3b03a0c4f0ba"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COHORTS_TABLE = "forecast_performance_cohorts"
_BENCHMARKS_TABLE = "forecast_performance_benchmarks"
_METHODOLOGIES_TABLE = "forecast_performance_methodologies"
_SNAPSHOTS_TABLE = "forecast_performance_snapshots"
_SNAPSHOT_MEMBERS_TABLE = "forecast_performance_snapshot_members"
_SNAPSHOT_EXCLUSIONS_TABLE = "forecast_performance_snapshot_exclusions"

_ALL_TABLES = (
    _SNAPSHOT_EXCLUSIONS_TABLE,
    _SNAPSHOT_MEMBERS_TABLE,
    _SNAPSHOTS_TABLE,
    _METHODOLOGIES_TABLE,
    _BENCHMARKS_TABLE,
    _COHORTS_TABLE,
)


def _timestamp_columns() -> list[sa.Column[Any]]:
    return [
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def _raise_if_downgrade_would_lose_data() -> None:
    bind = op.get_bind()
    non_empty: list[tuple[str, int]] = []
    for table in _ALL_TABLES:
        row_count: int = bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
        if row_count > 0:
            non_empty.append((table, row_count))
    if non_empty:
        details = ", ".join(f"{table}={count}" for table, count in non_empty)
        raise RuntimeError(
            f"Cannot downgrade migration {revision}: non-empty table(s) found ({details}). "
            "Dropping these tables would silently discard real forecast-performance history -- "
            "which cannot be reliably reconstructed after the fact. Downgrading past this "
            "migration once real data exists is a permanent limitation, not a bug -- restore "
            "from a backup instead."
        )


def upgrade() -> None:
    op.create_table(
        _COHORTS_TABLE,
        sa.Column("cohort_key", sa.String(), nullable=False),
        sa.Column("version_sequence", sa.Integer(), nullable=False),
        sa.Column("attribution_kind", sa.String(), nullable=False),
        sa.Column("originator_publisher_source_key", sa.String(), nullable=False),
        sa.Column("originator_forecaster_source_key", sa.String(), nullable=True),
        sa.Column("target_key", sa.String(), nullable=False),
        sa.Column("forecast_type", sa.String(), nullable=False),
        sa.Column("horizon_category", sa.String(), nullable=False),
        sa.Column("protocol_key", sa.String(), nullable=False),
        sa.Column("protocol_version_sequence", sa.Integer(), nullable=False),
        sa.Column("evaluation_mode", sa.String(), nullable=False),
        sa.Column("duplicate_selection_policy", sa.String(), nullable=False),
        sa.Column("issue_window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issue_window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "known_duplicate_evaluation_keys",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("availability", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rationale", sa.String(), nullable=False),
        sa.Column("correction_reason", sa.String(), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cohort_key", "version_sequence", name="uq_fpc_identity"),
        sa.ForeignKeyConstraint(
            ["originator_publisher_source_key"],
            ["intelligence_sources.source_key"],
            name="fk_fpc_originator_publisher",
        ),
        sa.ForeignKeyConstraint(
            ["originator_forecaster_source_key"],
            ["intelligence_sources.source_key"],
            name="fk_fpc_originator_forecaster",
        ),
        sa.ForeignKeyConstraint(
            ["protocol_key", "protocol_version_sequence"],
            [
                "forecast_evaluation_protocols.protocol_key",
                "forecast_evaluation_protocols.version_sequence",
            ],
            name="fk_fpc_protocol",
        ),
        sa.CheckConstraint("version_sequence >= 0", name="ck_fpc_version_sequence"),
        sa.CheckConstraint(
            "attribution_kind IN "
            "('NAMED_INSTITUTION', 'AGGREGATE_SURVEY_CONSENSUS', 'ANONYMOUS_RESPONDENT')",
            name="ck_fpc_attribution_kind",
        ),
        sa.CheckConstraint(
            "(attribution_kind = 'NAMED_INSTITUTION' AND originator_forecaster_source_key IS "
            "NOT NULL) OR "
            "(attribution_kind <> 'NAMED_INSTITUTION' AND originator_forecaster_source_key IS "
            "NULL)",
            name="ck_fpc_originator_shape",
        ),
        sa.CheckConstraint("target_key <> ''", name="ck_fpc_target_key"),
        sa.CheckConstraint(
            "forecast_type IN ('NUMERIC_POINT', 'CATEGORICAL_EVENT')", name="ck_fpc_forecast_type"
        ),
        sa.CheckConstraint("horizon_category <> ''", name="ck_fpc_horizon_category"),
        sa.CheckConstraint("protocol_key <> ''", name="ck_fpc_protocol_key"),
        sa.CheckConstraint(
            "protocol_version_sequence >= 0", name="ck_fpc_protocol_version_sequence"
        ),
        sa.CheckConstraint(
            "evaluation_mode IN ('PRODUCTION_OBSERVED', 'RETROSPECTIVE_RESEARCH')",
            name="ck_fpc_evaluation_mode",
        ),
        sa.CheckConstraint(
            "duplicate_selection_policy IN ('EARLIEST_QUALIFYING_ISSUE')",
            name="ck_fpc_duplicate_selection_policy",
        ),
        sa.CheckConstraint("rationale <> ''", name="ck_fpc_rationale"),
    )

    op.create_table(
        _BENCHMARKS_TABLE,
        sa.Column("benchmark_key", sa.String(), nullable=False),
        sa.Column("version_sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("target_key", sa.String(), nullable=False),
        sa.Column("horizon_category", sa.String(), nullable=False),
        sa.Column("metric", sa.String(), nullable=False),
        sa.Column("availability", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rationale", sa.String(), nullable=False),
        sa.Column("benchmark_cohort_key", sa.String(), nullable=True),
        sa.Column("benchmark_cohort_version_sequence", sa.Integer(), nullable=True),
        sa.Column("naive_categorical_class", sa.String(), nullable=True),
        sa.Column("naive_numeric_reference_value", sa.Numeric(), nullable=True),
        sa.Column("naive_numeric_reference_description", sa.String(), nullable=True),
        sa.Column("correction_reason", sa.String(), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("benchmark_key", "version_sequence", name="uq_fpb_identity"),
        sa.ForeignKeyConstraint(
            ["benchmark_cohort_key", "benchmark_cohort_version_sequence"],
            [f"{_COHORTS_TABLE}.cohort_key", f"{_COHORTS_TABLE}.version_sequence"],
            name="fk_fpb_benchmark_cohort",
        ),
        sa.CheckConstraint("version_sequence >= 0", name="ck_fpb_version_sequence"),
        sa.CheckConstraint(
            "kind IN ('AUTHENTICATED_SERIES', 'NAIVE_CATEGORICAL', 'NAIVE_NUMERIC')",
            name="ck_fpb_kind",
        ),
        sa.CheckConstraint("target_key <> ''", name="ck_fpb_target_key"),
        sa.CheckConstraint("horizon_category <> ''", name="ck_fpb_horizon_category"),
        sa.CheckConstraint(
            "metric IN ('NUMERIC_ERROR', 'CATEGORICAL_MATCH')", name="ck_fpb_metric"
        ),
        sa.CheckConstraint("rationale <> ''", name="ck_fpb_rationale"),
        sa.CheckConstraint(
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

    op.create_table(
        _METHODOLOGIES_TABLE,
        sa.Column("methodology_key", sa.String(), nullable=False),
        sa.Column("version_sequence", sa.Integer(), nullable=False),
        sa.Column("cohort_key", sa.String(), nullable=False),
        sa.Column("cohort_version_sequence", sa.Integer(), nullable=False),
        sa.Column("missing_data_policy", sa.String(), nullable=False),
        sa.Column("algorithm_version", sa.String(), nullable=False),
        sa.Column("availability", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rationale", sa.String(), nullable=False),
        sa.Column("benchmark_key", sa.String(), nullable=True),
        sa.Column("benchmark_version_sequence", sa.Integer(), nullable=True),
        sa.Column("correction_reason", sa.String(), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("methodology_key", "version_sequence", name="uq_fpm_identity"),
        sa.ForeignKeyConstraint(
            ["cohort_key", "cohort_version_sequence"],
            [f"{_COHORTS_TABLE}.cohort_key", f"{_COHORTS_TABLE}.version_sequence"],
            name="fk_fpm_cohort",
        ),
        sa.ForeignKeyConstraint(
            ["benchmark_key", "benchmark_version_sequence"],
            [f"{_BENCHMARKS_TABLE}.benchmark_key", f"{_BENCHMARKS_TABLE}.version_sequence"],
            name="fk_fpm_benchmark",
        ),
        sa.CheckConstraint("version_sequence >= 0", name="ck_fpm_version_sequence"),
        sa.CheckConstraint("cohort_version_sequence >= 0", name="ck_fpm_cohort_version_sequence"),
        sa.CheckConstraint(
            "missing_data_policy IN ('EXCLUDE_FROM_DENOMINATOR')",
            name="ck_fpm_missing_data_policy",
        ),
        sa.CheckConstraint("algorithm_version <> ''", name="ck_fpm_algorithm_version"),
        sa.CheckConstraint("rationale <> ''", name="ck_fpm_rationale"),
        sa.CheckConstraint(
            "(benchmark_key IS NULL AND benchmark_version_sequence IS NULL) OR "
            "(benchmark_key IS NOT NULL AND benchmark_version_sequence IS NOT NULL)",
            name="ck_fpm_benchmark_shape",
        ),
    )

    op.create_table(
        _SNAPSHOTS_TABLE,
        sa.Column("snapshot_key", sa.String(), nullable=False),
        sa.Column("revision_sequence", sa.Integer(), nullable=False),
        sa.Column("methodology_key", sa.String(), nullable=False),
        sa.Column("methodology_version_sequence", sa.Integer(), nullable=False),
        sa.Column("cohort_key", sa.String(), nullable=False),
        sa.Column("cohort_version_sequence", sa.Integer(), nullable=False),
        sa.Column("evaluation_mode", sa.String(), nullable=False),
        sa.Column("knowledge_cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("availability", sa.DateTime(timezone=True), nullable=False),
        sa.Column("algorithm_version", sa.String(), nullable=False),
        sa.Column("numeric_n", sa.Integer(), nullable=True),
        sa.Column("numeric_unit", sa.String(), nullable=True),
        sa.Column("numeric_mean_absolute_error", sa.Numeric(), nullable=True),
        sa.Column("numeric_mean_signed_error", sa.Numeric(), nullable=True),
        sa.Column("numeric_root_mean_squared_error", sa.Numeric(), nullable=True),
        sa.Column("categorical_n", sa.Integer(), nullable=True),
        sa.Column("categorical_match_count", sa.Integer(), nullable=True),
        sa.Column("categorical_mismatch_count", sa.Integer(), nullable=True),
        sa.Column("categorical_accuracy", sa.Numeric(), nullable=True),
        sa.Column("confusion_counts", postgresql.JSONB(), nullable=True),
        sa.Column("realized_class_distribution", postgresql.JSONB(), nullable=True),
        sa.Column("benchmark_status", sa.String(), nullable=False),
        sa.Column("benchmark_key", sa.String(), nullable=True),
        sa.Column("benchmark_version_sequence", sa.Integer(), nullable=True),
        sa.Column("benchmark_paired_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_mean_absolute_error", sa.Numeric(), nullable=True),
        sa.Column("benchmark_mean_absolute_error", sa.Numeric(), nullable=True),
        sa.Column("mean_absolute_error_difference", sa.Numeric(), nullable=True),
        sa.Column("relative_mae_improvement", sa.Numeric(), nullable=True),
        sa.Column("source_accuracy", sa.Numeric(), nullable=True),
        sa.Column("benchmark_accuracy", sa.Numeric(), nullable=True),
        sa.Column("accuracy_difference", sa.Numeric(), nullable=True),
        sa.Column("diag_raw_candidate_count", sa.Integer(), nullable=False),
        sa.Column("diag_accepted_count", sa.Integer(), nullable=False),
        sa.Column("diag_unique_forecast_issue_count", sa.Integer(), nullable=False),
        sa.Column("diag_unique_target_event_count", sa.Integer(), nullable=False),
        sa.Column("diag_distinct_target_period_count", sa.Integer(), nullable=False),
        sa.Column("diag_production_count", sa.Integer(), nullable=False),
        sa.Column("diag_research_count", sa.Integer(), nullable=False),
        sa.Column("diag_missing_outcome_rate", sa.Numeric(), nullable=False),
        sa.Column("diag_earliest_availability", sa.DateTime(timezone=True), nullable=True),
        sa.Column("diag_latest_availability", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sample_adequacy", sa.String(), nullable=False),
        sa.Column("correction_reason", sa.String(), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_key", "revision_sequence", name="uq_fps_identity"),
        sa.ForeignKeyConstraint(
            ["cohort_key", "cohort_version_sequence"],
            [f"{_COHORTS_TABLE}.cohort_key", f"{_COHORTS_TABLE}.version_sequence"],
            name="fk_fps_cohort",
        ),
        sa.ForeignKeyConstraint(
            ["methodology_key", "methodology_version_sequence"],
            [f"{_METHODOLOGIES_TABLE}.methodology_key", f"{_METHODOLOGIES_TABLE}.version_sequence"],
            name="fk_fps_methodology",
        ),
        sa.CheckConstraint("revision_sequence >= 0", name="ck_fps_revision_sequence"),
        sa.CheckConstraint("cohort_version_sequence >= 0", name="ck_fps_cohort_version_sequence"),
        sa.CheckConstraint(
            "methodology_version_sequence >= 0", name="ck_fps_methodology_version_sequence"
        ),
        sa.CheckConstraint(
            "evaluation_mode IN ('PRODUCTION_OBSERVED', 'RETROSPECTIVE_RESEARCH')",
            name="ck_fps_evaluation_mode",
        ),
        sa.CheckConstraint("algorithm_version <> ''", name="ck_fps_algorithm_version"),
        sa.CheckConstraint(
            "(numeric_n IS NULL OR categorical_n IS NULL)", name="ck_fps_summary_exclusive"
        ),
        sa.CheckConstraint(
            "benchmark_status IN ('COMPARED', 'BENCHMARK_UNAVAILABLE')",
            name="ck_fps_benchmark_status",
        ),
        sa.CheckConstraint(
            "sample_adequacy IN "
            "('INSUFFICIENT_DATA', 'DESCRIPTIVE_ONLY', 'COMPARABLE_SAMPLE', 'INFERENCE_SUPPORTED')",
            name="ck_fps_sample_adequacy",
        ),
    )

    op.create_table(
        _SNAPSHOT_MEMBERS_TABLE,
        sa.Column("snapshot_key", sa.String(), nullable=False),
        sa.Column("snapshot_revision_sequence", sa.Integer(), nullable=False),
        sa.Column("evaluation_key", sa.String(), nullable=False),
        sa.Column("evaluation_revision_sequence", sa.Integer(), nullable=False),
        sa.Column("forecast_claim_key", sa.String(), nullable=False),
        sa.Column("forecast_revision_sequence", sa.Integer(), nullable=False),
        sa.Column("outcome_key", sa.String(), nullable=False),
        sa.Column("outcome_revision_sequence", sa.Integer(), nullable=False),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "snapshot_key", "snapshot_revision_sequence", "evaluation_key", name="uq_fpsm_identity"
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_key", "snapshot_revision_sequence"],
            [f"{_SNAPSHOTS_TABLE}.snapshot_key", f"{_SNAPSHOTS_TABLE}.revision_sequence"],
            name="fk_fpsm_snapshot",
        ),
        sa.CheckConstraint(
            "snapshot_revision_sequence >= 0", name="ck_fpsm_snapshot_revision_sequence"
        ),
        sa.CheckConstraint("evaluation_revision_sequence >= 0", name="ck_fpsm_evaluation_revision"),
        sa.CheckConstraint("forecast_revision_sequence >= 0", name="ck_fpsm_forecast_revision"),
        sa.CheckConstraint("outcome_revision_sequence >= 0", name="ck_fpsm_outcome_revision"),
    )

    op.create_table(
        _SNAPSHOT_EXCLUSIONS_TABLE,
        sa.Column("snapshot_key", sa.String(), nullable=False),
        sa.Column("snapshot_revision_sequence", sa.Integer(), nullable=False),
        sa.Column("evaluation_key", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "snapshot_key", "snapshot_revision_sequence", "evaluation_key", name="uq_fpse_identity"
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_key", "snapshot_revision_sequence"],
            [f"{_SNAPSHOTS_TABLE}.snapshot_key", f"{_SNAPSHOTS_TABLE}.revision_sequence"],
            name="fk_fpse_snapshot",
        ),
        sa.CheckConstraint(
            "snapshot_revision_sequence >= 0", name="ck_fpse_snapshot_revision_sequence"
        ),
    )


def downgrade() -> None:
    _raise_if_downgrade_would_lose_data()
    op.drop_table(_SNAPSHOT_EXCLUSIONS_TABLE)
    op.drop_table(_SNAPSHOT_MEMBERS_TABLE)
    op.drop_table(_SNAPSHOTS_TABLE)
    op.drop_table(_METHODOLOGIES_TABLE)
    op.drop_table(_BENCHMARKS_TABLE)
    op.drop_table(_COHORTS_TABLE)
