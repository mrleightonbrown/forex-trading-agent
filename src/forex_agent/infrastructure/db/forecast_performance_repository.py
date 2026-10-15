"""SQLAlchemy implementation of `ForecastPerformanceRepository`
(FX-66). Mirrors `SqlAlchemyForecastOutcomeRepository`/`SqlAlchemy
ForecastEvaluationRepository`'s own flattening and idempotent-insert
conventions exactly. The snapshot write is the one genuinely multi-
statement operation here (main row + member rows + exclusion rows,
all in the SAME uncommitted transaction, committed together) -- never
partially visible."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import ColumnElement, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from forex_agent.application.ports.forecast_performance_repository import (
    ForecastPerformanceBenchmarkWriteResult,
    ForecastPerformanceCohortWriteResult,
    ForecastPerformanceMethodologyWriteResult,
    ForecastPerformanceSnapshotWriteResult,
)
from forex_agent.domain.forecast_attribution_kind import ForecastAttributionKind
from forex_agent.domain.forecast_evaluation_metric import ForecastEvaluationMetric
from forex_agent.domain.forecast_performance_benchmark_comparison import (
    ForecastPerformanceBenchmarkComparison,
)
from forex_agent.domain.forecast_performance_benchmark_comparison_status import (
    ForecastPerformanceBenchmarkComparisonStatus,
)
from forex_agent.domain.forecast_performance_benchmark_definition import (
    ForecastPerformanceBenchmarkDefinition,
)
from forex_agent.domain.forecast_performance_benchmark_kind import (
    ForecastPerformanceBenchmarkKind,
)
from forex_agent.domain.forecast_performance_categorical_summary import (
    ForecastPerformanceCategoricalSummary,
)
from forex_agent.domain.forecast_performance_cohort_definition import (
    ForecastPerformanceCohortDefinition,
)
from forex_agent.domain.forecast_performance_duplicate_selection_policy import (
    ForecastPerformanceDuplicateSelectionPolicy,
)
from forex_agent.domain.forecast_performance_exclusion_reason import (
    ForecastPerformanceExclusionReason,
)
from forex_agent.domain.forecast_performance_methodology import ForecastPerformanceMethodology
from forex_agent.domain.forecast_performance_missing_data_policy import (
    ForecastPerformanceMissingDataPolicy,
)
from forex_agent.domain.forecast_performance_numeric_summary import (
    ForecastPerformanceNumericSummary,
)
from forex_agent.domain.forecast_performance_sample_adequacy import (
    ForecastPerformanceSampleAdequacy,
)
from forex_agent.domain.forecast_performance_sample_diagnostics import (
    ForecastPerformanceSampleDiagnostics,
)
from forex_agent.domain.forecast_performance_snapshot import (
    ForecastPerformanceSnapshot,
    ForecastPerformanceSnapshotMember,
)
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.models.forecast_performance_benchmark import (
    ForecastPerformanceBenchmarkRow,
)
from forex_agent.infrastructure.db.models.forecast_performance_cohort import (
    ForecastPerformanceCohortRow,
)
from forex_agent.infrastructure.db.models.forecast_performance_methodology import (
    ForecastPerformanceMethodologyRow,
)
from forex_agent.infrastructure.db.models.forecast_performance_snapshot import (
    ForecastPerformanceSnapshotExclusionRow,
    ForecastPerformanceSnapshotMemberRow,
    ForecastPerformanceSnapshotRow,
)

_COHORT_KEY = ("cohort_key", "version_sequence")
_BENCHMARK_KEY = ("benchmark_key", "version_sequence")
_METHODOLOGY_KEY = ("methodology_key", "version_sequence")
_SNAPSHOT_KEY = ("snapshot_key", "revision_sequence")


class MalformedForecastPerformanceRowError(Exception):
    def __init__(self, field: str, value: object) -> None:
        self.field = field
        self.value = value
        super().__init__(f"stored forecast_performance row {field}={value!r} is unknown")


def _dt(value: datetime | None) -> UtcTimestamp | None:
    return None if value is None else UtcTimestamp(value)


class SqlAlchemyForecastPerformanceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- cohorts -------------------------------------------------------

    async def latest_cohort_version(
        self, cohort_key: str
    ) -> ForecastPerformanceCohortDefinition | None:
        stmt = (
            select(ForecastPerformanceCohortRow)
            .where(ForecastPerformanceCohortRow.cohort_key == cohort_key)
            .order_by(ForecastPerformanceCohortRow.version_sequence.desc())
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        await self._session.commit()
        return None if row is None else _cohort_row_to_domain(row)

    async def list_cohort_versions(
        self, cohort_key: str
    ) -> tuple[ForecastPerformanceCohortDefinition, ...]:
        stmt = select(ForecastPerformanceCohortRow).where(
            ForecastPerformanceCohortRow.cohort_key == cohort_key
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        await self._session.commit()
        return tuple(_cohort_row_to_domain(row) for row in rows)

    async def add_cohort_version(
        self, cohort: ForecastPerformanceCohortDefinition
    ) -> ForecastPerformanceCohortWriteResult:
        stmt = (
            pg_insert(ForecastPerformanceCohortRow)
            .values(_cohort_row_values(cohort))
            .on_conflict_do_nothing(index_elements=list(_COHORT_KEY))
            .returning(ForecastPerformanceCohortRow.id)
        )
        inserted_id = (await self._session.execute(stmt)).scalar_one_or_none()
        await self._session.commit()
        return ForecastPerformanceCohortWriteResult(inserted=inserted_id is not None)

    # --- benchmarks ------------------------------------------------------

    async def latest_benchmark_version(
        self, benchmark_key: str
    ) -> ForecastPerformanceBenchmarkDefinition | None:
        stmt = (
            select(ForecastPerformanceBenchmarkRow)
            .where(ForecastPerformanceBenchmarkRow.benchmark_key == benchmark_key)
            .order_by(ForecastPerformanceBenchmarkRow.version_sequence.desc())
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        await self._session.commit()
        return None if row is None else _benchmark_row_to_domain(row)

    async def list_benchmark_versions(
        self, benchmark_key: str
    ) -> tuple[ForecastPerformanceBenchmarkDefinition, ...]:
        stmt = select(ForecastPerformanceBenchmarkRow).where(
            ForecastPerformanceBenchmarkRow.benchmark_key == benchmark_key
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        await self._session.commit()
        return tuple(_benchmark_row_to_domain(row) for row in rows)

    async def add_benchmark_version(
        self, benchmark: ForecastPerformanceBenchmarkDefinition
    ) -> ForecastPerformanceBenchmarkWriteResult:
        stmt = (
            pg_insert(ForecastPerformanceBenchmarkRow)
            .values(_benchmark_row_values(benchmark))
            .on_conflict_do_nothing(index_elements=list(_BENCHMARK_KEY))
            .returning(ForecastPerformanceBenchmarkRow.id)
        )
        inserted_id = (await self._session.execute(stmt)).scalar_one_or_none()
        await self._session.commit()
        return ForecastPerformanceBenchmarkWriteResult(inserted=inserted_id is not None)

    # --- methodologies ---------------------------------------------------

    async def latest_methodology_version(
        self, methodology_key: str
    ) -> ForecastPerformanceMethodology | None:
        stmt = (
            select(ForecastPerformanceMethodologyRow)
            .where(ForecastPerformanceMethodologyRow.methodology_key == methodology_key)
            .order_by(ForecastPerformanceMethodologyRow.version_sequence.desc())
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        await self._session.commit()
        return None if row is None else _methodology_row_to_domain(row)

    async def list_methodology_versions(
        self, methodology_key: str
    ) -> tuple[ForecastPerformanceMethodology, ...]:
        stmt = select(ForecastPerformanceMethodologyRow).where(
            ForecastPerformanceMethodologyRow.methodology_key == methodology_key
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        await self._session.commit()
        return tuple(_methodology_row_to_domain(row) for row in rows)

    async def add_methodology_version(
        self, methodology: ForecastPerformanceMethodology
    ) -> ForecastPerformanceMethodologyWriteResult:
        stmt = (
            pg_insert(ForecastPerformanceMethodologyRow)
            .values(_methodology_row_values(methodology))
            .on_conflict_do_nothing(index_elements=list(_METHODOLOGY_KEY))
            .returning(ForecastPerformanceMethodologyRow.id)
        )
        inserted_id = (await self._session.execute(stmt)).scalar_one_or_none()
        await self._session.commit()
        return ForecastPerformanceMethodologyWriteResult(inserted=inserted_id is not None)

    # --- snapshots ---------------------------------------------------------

    async def latest_snapshot_vintage(
        self, snapshot_key: str
    ) -> ForecastPerformanceSnapshot | None:
        return await self._select_latest_snapshot(
            [ForecastPerformanceSnapshotRow.snapshot_key == snapshot_key]
        )

    async def list_vintages_for_snapshot(
        self, snapshot_key: str
    ) -> tuple[ForecastPerformanceSnapshot, ...]:
        stmt = select(ForecastPerformanceSnapshotRow).where(
            ForecastPerformanceSnapshotRow.snapshot_key == snapshot_key
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        await self._session.commit()
        return tuple([await self._hydrate_snapshot(row) for row in rows])

    async def add_snapshot_vintage(
        self, snapshot: ForecastPerformanceSnapshot
    ) -> ForecastPerformanceSnapshotWriteResult:
        stmt = (
            pg_insert(ForecastPerformanceSnapshotRow)
            .values(_snapshot_row_values(snapshot))
            .on_conflict_do_nothing(index_elements=list(_SNAPSHOT_KEY))
            .returning(ForecastPerformanceSnapshotRow.id)
        )
        inserted_id = (await self._session.execute(stmt)).scalar_one_or_none()
        if inserted_id is None:
            await self._session.rollback()
            return ForecastPerformanceSnapshotWriteResult(inserted=False)

        if snapshot.members:
            await self._session.execute(
                pg_insert(ForecastPerformanceSnapshotMemberRow).values(
                    [
                        _member_row_values(snapshot.snapshot_key, snapshot.revision_sequence, m)
                        for m in snapshot.members
                    ]
                )
            )
        if snapshot.exclusions:
            await self._session.execute(
                pg_insert(ForecastPerformanceSnapshotExclusionRow).values(
                    [
                        _exclusion_row_values(
                            snapshot.snapshot_key, snapshot.revision_sequence, key, reason
                        )
                        for key, reason in snapshot.exclusions
                    ]
                )
            )
        await self._session.commit()
        return ForecastPerformanceSnapshotWriteResult(inserted=True)

    async def latest_production_observed_snapshot_as_of(
        self, snapshot_key: str, as_of: UtcTimestamp
    ) -> ForecastPerformanceSnapshot | None:
        return await self._select_latest_snapshot(
            [
                ForecastPerformanceSnapshotRow.snapshot_key == snapshot_key,
                ForecastPerformanceSnapshotRow.evaluation_mode
                == ForecastProvenanceMode.PRODUCTION_OBSERVED.value,
                ForecastPerformanceSnapshotRow.availability <= as_of.value,
            ]
        )

    async def latest_snapshot_as_of_for_research(
        self, snapshot_key: str, research_as_of: UtcTimestamp
    ) -> ForecastPerformanceSnapshot | None:
        return await self._select_latest_snapshot(
            [
                ForecastPerformanceSnapshotRow.snapshot_key == snapshot_key,
                ForecastPerformanceSnapshotRow.availability <= research_as_of.value,
            ]
        )

    async def _select_latest_snapshot(
        self, conditions: list[ColumnElement[bool]]
    ) -> ForecastPerformanceSnapshot | None:
        stmt = (
            select(ForecastPerformanceSnapshotRow)
            .where(*conditions)
            .order_by(
                ForecastPerformanceSnapshotRow.availability.desc(),
                ForecastPerformanceSnapshotRow.revision_sequence.desc(),
            )
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        await self._session.commit()
        return None if row is None else await self._hydrate_snapshot(row)

    async def _hydrate_snapshot(
        self, row: ForecastPerformanceSnapshotRow
    ) -> ForecastPerformanceSnapshot:
        member_rows = (
            (
                await self._session.execute(
                    select(ForecastPerformanceSnapshotMemberRow).where(
                        ForecastPerformanceSnapshotMemberRow.snapshot_key == row.snapshot_key,
                        ForecastPerformanceSnapshotMemberRow.snapshot_revision_sequence
                        == row.revision_sequence,
                    )
                )
            )
            .scalars()
            .all()
        )
        exclusion_rows = (
            (
                await self._session.execute(
                    select(ForecastPerformanceSnapshotExclusionRow).where(
                        ForecastPerformanceSnapshotExclusionRow.snapshot_key == row.snapshot_key,
                        ForecastPerformanceSnapshotExclusionRow.snapshot_revision_sequence
                        == row.revision_sequence,
                    )
                )
            )
            .scalars()
            .all()
        )
        await self._session.commit()
        return _snapshot_row_to_domain(row, list(member_rows), list(exclusion_rows))


def _cohort_row_values(cohort: ForecastPerformanceCohortDefinition) -> dict[str, object]:
    return {
        "cohort_key": cohort.cohort_key,
        "version_sequence": cohort.version_sequence,
        "attribution_kind": cohort.attribution_kind.value,
        "originator_publisher_source_key": cohort.originator_publisher_source_key,
        "originator_forecaster_source_key": cohort.originator_forecaster_source_key,
        "target_key": cohort.target_key,
        "forecast_type": cohort.forecast_type.value,
        "horizon_category": cohort.horizon_category,
        "protocol_key": cohort.protocol_key,
        "protocol_version_sequence": cohort.protocol_version_sequence,
        "evaluation_mode": cohort.evaluation_mode.value,
        "duplicate_selection_policy": cohort.duplicate_selection_policy.value,
        "issue_window_start": cohort.issue_window_start.value
        if cohort.issue_window_start
        else None,
        "issue_window_end": cohort.issue_window_end.value if cohort.issue_window_end else None,
        "known_duplicate_evaluation_keys": list(cohort.known_duplicate_evaluation_keys),
        "availability": cohort.availability.value,
        "rationale": cohort.rationale,
        "correction_reason": cohort.correction_reason,
    }


def _cohort_row_to_domain(row: ForecastPerformanceCohortRow) -> ForecastPerformanceCohortDefinition:
    try:
        attribution_kind = ForecastAttributionKind(row.attribution_kind)
    except ValueError as exc:
        raise MalformedForecastPerformanceRowError(
            "attribution_kind", row.attribution_kind
        ) from exc
    try:
        forecast_type = ForecastType(row.forecast_type)
    except ValueError as exc:
        raise MalformedForecastPerformanceRowError("forecast_type", row.forecast_type) from exc
    try:
        evaluation_mode = ForecastProvenanceMode(row.evaluation_mode)
    except ValueError as exc:
        raise MalformedForecastPerformanceRowError("evaluation_mode", row.evaluation_mode) from exc
    try:
        duplicate_policy = ForecastPerformanceDuplicateSelectionPolicy(
            row.duplicate_selection_policy
        )
    except ValueError as exc:
        raise MalformedForecastPerformanceRowError(
            "duplicate_selection_policy", row.duplicate_selection_policy
        ) from exc
    return ForecastPerformanceCohortDefinition(
        cohort_key=row.cohort_key,
        version_sequence=row.version_sequence,
        attribution_kind=attribution_kind,
        originator_publisher_source_key=row.originator_publisher_source_key,
        originator_forecaster_source_key=row.originator_forecaster_source_key,
        target_key=row.target_key,
        forecast_type=forecast_type,
        horizon_category=row.horizon_category,
        protocol_key=row.protocol_key,
        protocol_version_sequence=row.protocol_version_sequence,
        evaluation_mode=evaluation_mode,
        duplicate_selection_policy=duplicate_policy,
        issue_window_start=_dt(row.issue_window_start),
        issue_window_end=_dt(row.issue_window_end),
        known_duplicate_evaluation_keys=tuple(row.known_duplicate_evaluation_keys),
        availability=UtcTimestamp(row.availability),
        rationale=row.rationale,
        correction_reason=row.correction_reason,
    )


def _benchmark_row_values(benchmark: ForecastPerformanceBenchmarkDefinition) -> dict[str, object]:
    return {
        "benchmark_key": benchmark.benchmark_key,
        "version_sequence": benchmark.version_sequence,
        "kind": benchmark.kind.value,
        "target_key": benchmark.target_key,
        "horizon_category": benchmark.horizon_category,
        "metric": benchmark.metric.value,
        "availability": benchmark.availability.value,
        "rationale": benchmark.rationale,
        "benchmark_cohort_key": benchmark.benchmark_cohort_key,
        "benchmark_cohort_version_sequence": benchmark.benchmark_cohort_version_sequence,
        "naive_categorical_class": benchmark.naive_categorical_class,
        "naive_numeric_reference_value": benchmark.naive_numeric_reference_value,
        "naive_numeric_reference_description": benchmark.naive_numeric_reference_description,
        "correction_reason": benchmark.correction_reason,
    }


def _benchmark_row_to_domain(
    row: ForecastPerformanceBenchmarkRow,
) -> ForecastPerformanceBenchmarkDefinition:
    try:
        kind = ForecastPerformanceBenchmarkKind(row.kind)
    except ValueError as exc:
        raise MalformedForecastPerformanceRowError("kind", row.kind) from exc
    try:
        metric = ForecastEvaluationMetric(row.metric)
    except ValueError as exc:
        raise MalformedForecastPerformanceRowError("metric", row.metric) from exc
    return ForecastPerformanceBenchmarkDefinition(
        benchmark_key=row.benchmark_key,
        version_sequence=row.version_sequence,
        kind=kind,
        target_key=row.target_key,
        horizon_category=row.horizon_category,
        metric=metric,
        availability=UtcTimestamp(row.availability),
        rationale=row.rationale,
        benchmark_cohort_key=row.benchmark_cohort_key,
        benchmark_cohort_version_sequence=row.benchmark_cohort_version_sequence,
        naive_categorical_class=row.naive_categorical_class,
        naive_numeric_reference_value=(
            Decimal(row.naive_numeric_reference_value)
            if row.naive_numeric_reference_value is not None
            else None
        ),
        naive_numeric_reference_description=row.naive_numeric_reference_description,
        correction_reason=row.correction_reason,
    )


def _methodology_row_values(methodology: ForecastPerformanceMethodology) -> dict[str, object]:
    return {
        "methodology_key": methodology.methodology_key,
        "version_sequence": methodology.version_sequence,
        "cohort_key": methodology.cohort_key,
        "cohort_version_sequence": methodology.cohort_version_sequence,
        "missing_data_policy": methodology.missing_data_policy.value,
        "algorithm_version": methodology.algorithm_version,
        "availability": methodology.availability.value,
        "rationale": methodology.rationale,
        "benchmark_key": methodology.benchmark_key,
        "benchmark_version_sequence": methodology.benchmark_version_sequence,
        "correction_reason": methodology.correction_reason,
    }


def _methodology_row_to_domain(
    row: ForecastPerformanceMethodologyRow,
) -> ForecastPerformanceMethodology:
    try:
        missing_data_policy = ForecastPerformanceMissingDataPolicy(row.missing_data_policy)
    except ValueError as exc:
        raise MalformedForecastPerformanceRowError(
            "missing_data_policy", row.missing_data_policy
        ) from exc
    return ForecastPerformanceMethodology(
        methodology_key=row.methodology_key,
        version_sequence=row.version_sequence,
        cohort_key=row.cohort_key,
        cohort_version_sequence=row.cohort_version_sequence,
        missing_data_policy=missing_data_policy,
        algorithm_version=row.algorithm_version,
        availability=UtcTimestamp(row.availability),
        rationale=row.rationale,
        benchmark_key=row.benchmark_key,
        benchmark_version_sequence=row.benchmark_version_sequence,
        correction_reason=row.correction_reason,
    )


def _member_row_values(
    snapshot_key: str, snapshot_revision_sequence: int, member: ForecastPerformanceSnapshotMember
) -> dict[str, object]:
    return {
        "snapshot_key": snapshot_key,
        "snapshot_revision_sequence": snapshot_revision_sequence,
        "evaluation_key": member.evaluation_key,
        "evaluation_revision_sequence": member.evaluation_revision_sequence,
        "forecast_claim_key": member.forecast_claim_key,
        "forecast_revision_sequence": member.forecast_revision_sequence,
        "outcome_key": member.outcome_key,
        "outcome_revision_sequence": member.outcome_revision_sequence,
    }


def _exclusion_row_values(
    snapshot_key: str,
    snapshot_revision_sequence: int,
    evaluation_key: str,
    reason: ForecastPerformanceExclusionReason,
) -> dict[str, object]:
    return {
        "snapshot_key": snapshot_key,
        "snapshot_revision_sequence": snapshot_revision_sequence,
        "evaluation_key": evaluation_key,
        "reason": reason.value,
    }


def _snapshot_row_values(snapshot: ForecastPerformanceSnapshot) -> dict[str, object]:
    numeric = snapshot.numeric_summary
    categorical = snapshot.categorical_summary
    comparison = snapshot.benchmark_comparison
    diagnostics = snapshot.diagnostics
    return {
        "snapshot_key": snapshot.snapshot_key,
        "revision_sequence": snapshot.revision_sequence,
        "methodology_key": snapshot.methodology_key,
        "methodology_version_sequence": snapshot.methodology_version_sequence,
        "cohort_key": snapshot.cohort_key,
        "cohort_version_sequence": snapshot.cohort_version_sequence,
        "evaluation_mode": snapshot.evaluation_mode.value,
        "knowledge_cutoff": snapshot.knowledge_cutoff.value,
        "availability": snapshot.availability.value,
        "algorithm_version": snapshot.algorithm_version,
        "numeric_n": numeric.n if numeric else None,
        "numeric_unit": numeric.unit if numeric else None,
        "numeric_mean_absolute_error": numeric.mean_absolute_error if numeric else None,
        "numeric_mean_signed_error": numeric.mean_signed_error if numeric else None,
        "numeric_root_mean_squared_error": numeric.root_mean_squared_error if numeric else None,
        "categorical_n": categorical.n if categorical else None,
        "categorical_match_count": categorical.match_count if categorical else None,
        "categorical_mismatch_count": categorical.mismatch_count if categorical else None,
        "categorical_accuracy": categorical.accuracy if categorical else None,
        "confusion_counts": (
            [list(t) for t in categorical.confusion_counts] if categorical else None
        ),
        "realized_class_distribution": (
            [list(t) for t in categorical.realized_class_distribution] if categorical else None
        ),
        "benchmark_status": comparison.status.value,
        "benchmark_key": comparison.benchmark_key,
        "benchmark_version_sequence": comparison.benchmark_version_sequence,
        "benchmark_paired_count": comparison.paired_count,
        "source_mean_absolute_error": comparison.source_mean_absolute_error,
        "benchmark_mean_absolute_error": comparison.benchmark_mean_absolute_error,
        "mean_absolute_error_difference": comparison.mean_absolute_error_difference,
        "relative_mae_improvement": comparison.relative_mae_improvement,
        "source_accuracy": comparison.source_accuracy,
        "benchmark_accuracy": comparison.benchmark_accuracy,
        "accuracy_difference": comparison.accuracy_difference,
        "diag_raw_candidate_count": diagnostics.raw_candidate_count,
        "diag_accepted_count": diagnostics.accepted_count,
        "diag_unique_forecast_issue_count": diagnostics.unique_forecast_issue_count,
        "diag_unique_target_event_count": diagnostics.unique_target_event_count,
        "diag_distinct_target_period_count": diagnostics.distinct_target_period_count,
        "diag_production_count": diagnostics.production_count,
        "diag_research_count": diagnostics.research_count,
        "diag_missing_outcome_rate": diagnostics.missing_outcome_rate,
        "diag_earliest_availability": (
            diagnostics.earliest_availability.value if diagnostics.earliest_availability else None
        ),
        "diag_latest_availability": (
            diagnostics.latest_availability.value if diagnostics.latest_availability else None
        ),
        "sample_adequacy": diagnostics.sample_adequacy.value,
        "correction_reason": snapshot.correction_reason,
    }


def _snapshot_row_to_domain(
    row: ForecastPerformanceSnapshotRow,
    member_rows: list[ForecastPerformanceSnapshotMemberRow],
    exclusion_rows: list[ForecastPerformanceSnapshotExclusionRow],
) -> ForecastPerformanceSnapshot:
    try:
        evaluation_mode = ForecastProvenanceMode(row.evaluation_mode)
    except ValueError as exc:
        raise MalformedForecastPerformanceRowError("evaluation_mode", row.evaluation_mode) from exc
    try:
        benchmark_status = ForecastPerformanceBenchmarkComparisonStatus(row.benchmark_status)
    except ValueError as exc:
        raise MalformedForecastPerformanceRowError(
            "benchmark_status", row.benchmark_status
        ) from exc
    try:
        sample_adequacy = ForecastPerformanceSampleAdequacy(row.sample_adequacy)
    except ValueError as exc:
        raise MalformedForecastPerformanceRowError("sample_adequacy", row.sample_adequacy) from exc

    members = tuple(
        ForecastPerformanceSnapshotMember(
            evaluation_key=m.evaluation_key,
            evaluation_revision_sequence=m.evaluation_revision_sequence,
            forecast_claim_key=m.forecast_claim_key,
            forecast_revision_sequence=m.forecast_revision_sequence,
            outcome_key=m.outcome_key,
            outcome_revision_sequence=m.outcome_revision_sequence,
        )
        for m in sorted(member_rows, key=lambda r: r.evaluation_key)
    )
    exclusions = tuple(
        (e.evaluation_key, ForecastPerformanceExclusionReason(e.reason))
        for e in sorted(exclusion_rows, key=lambda r: r.evaluation_key)
    )

    numeric_summary: ForecastPerformanceNumericSummary | None = None
    if row.numeric_n is not None:
        assert row.numeric_unit is not None
        assert row.numeric_mean_absolute_error is not None
        assert row.numeric_mean_signed_error is not None
        assert row.numeric_root_mean_squared_error is not None
        numeric_summary = ForecastPerformanceNumericSummary(
            n=row.numeric_n,
            unit=row.numeric_unit,
            mean_absolute_error=Decimal(row.numeric_mean_absolute_error),
            mean_signed_error=Decimal(row.numeric_mean_signed_error),
            root_mean_squared_error=Decimal(row.numeric_root_mean_squared_error),
        )

    categorical_summary: ForecastPerformanceCategoricalSummary | None = None
    if row.categorical_n is not None:
        assert row.categorical_match_count is not None
        assert row.categorical_mismatch_count is not None
        assert row.categorical_accuracy is not None
        confusion_counts: tuple[tuple[str, str, int], ...] = tuple(
            (str(p), str(o), int(str(c))) for p, o, c in (row.confusion_counts or [])
        )
        realized_class_distribution: tuple[tuple[str, int], ...] = tuple(
            (str(o), int(str(c))) for o, c in (row.realized_class_distribution or [])
        )
        categorical_summary = ForecastPerformanceCategoricalSummary(
            n=row.categorical_n,
            match_count=row.categorical_match_count,
            mismatch_count=row.categorical_mismatch_count,
            accuracy=Decimal(row.categorical_accuracy),
            confusion_counts=confusion_counts,
            realized_class_distribution=realized_class_distribution,
        )
    benchmark_comparison = ForecastPerformanceBenchmarkComparison(
        status=benchmark_status,
        benchmark_key=row.benchmark_key,
        benchmark_version_sequence=row.benchmark_version_sequence,
        paired_count=row.benchmark_paired_count,
        source_mean_absolute_error=(
            Decimal(row.source_mean_absolute_error)
            if row.source_mean_absolute_error is not None
            else None
        ),
        benchmark_mean_absolute_error=(
            Decimal(row.benchmark_mean_absolute_error)
            if row.benchmark_mean_absolute_error is not None
            else None
        ),
        mean_absolute_error_difference=(
            Decimal(row.mean_absolute_error_difference)
            if row.mean_absolute_error_difference is not None
            else None
        ),
        relative_mae_improvement=(
            Decimal(row.relative_mae_improvement)
            if row.relative_mae_improvement is not None
            else None
        ),
        source_accuracy=Decimal(row.source_accuracy) if row.source_accuracy is not None else None,
        benchmark_accuracy=(
            Decimal(row.benchmark_accuracy) if row.benchmark_accuracy is not None else None
        ),
        accuracy_difference=(
            Decimal(row.accuracy_difference) if row.accuracy_difference is not None else None
        ),
    )
    diagnostics = ForecastPerformanceSampleDiagnostics(
        raw_candidate_count=row.diag_raw_candidate_count,
        accepted_count=row.diag_accepted_count,
        excluded_by_reason=tuple(
            sorted(
                (
                    (reason, sum(1 for _, r in exclusions if r is reason))
                    for reason in {r for _, r in exclusions}
                ),
                key=lambda pair: pair[0].value,
            )
        ),
        unique_forecast_issue_count=row.diag_unique_forecast_issue_count,
        unique_target_event_count=row.diag_unique_target_event_count,
        distinct_target_period_count=row.diag_distinct_target_period_count,
        benchmark_paired_count=row.benchmark_paired_count,
        production_count=row.diag_production_count,
        research_count=row.diag_research_count,
        missing_outcome_rate=Decimal(row.diag_missing_outcome_rate),
        earliest_availability=_dt(row.diag_earliest_availability),
        latest_availability=_dt(row.diag_latest_availability),
        sample_adequacy=sample_adequacy,
    )

    return ForecastPerformanceSnapshot(
        snapshot_key=row.snapshot_key,
        revision_sequence=row.revision_sequence,
        methodology_key=row.methodology_key,
        methodology_version_sequence=row.methodology_version_sequence,
        cohort_key=row.cohort_key,
        cohort_version_sequence=row.cohort_version_sequence,
        evaluation_mode=evaluation_mode,
        members=members,
        exclusions=exclusions,
        benchmark_comparison=benchmark_comparison,
        diagnostics=diagnostics,
        knowledge_cutoff=UtcTimestamp(row.knowledge_cutoff),
        availability=UtcTimestamp(row.availability),
        algorithm_version=row.algorithm_version,
        numeric_summary=numeric_summary,
        categorical_summary=categorical_summary,
        correction_reason=row.correction_reason,
    )
