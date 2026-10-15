"""FX-66 Section 16/20.G: tests for `RecordForecastPerformanceSnapshot`
-- full-history determinism, idempotent exact-repeat, PIT ordering,
and "the same complete basis never produces two different results."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.application.use_cases.record_forecast_performance_snapshot import (
    ForecastPerformanceSnapshotDeterminismError,
    ForecastPerformanceSnapshotOutcome,
    OutOfOrderForecastPerformanceSnapshotError,
    RecordForecastPerformanceSnapshot,
)
from forex_agent.domain.forecast_performance_benchmark_comparison import (
    ForecastPerformanceBenchmarkComparison,
)
from forex_agent.domain.forecast_performance_benchmark_comparison_status import (
    ForecastPerformanceBenchmarkComparisonStatus,
)
from forex_agent.domain.forecast_performance_exclusion_reason import (
    ForecastPerformanceExclusionReason,
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
from forex_agent.domain.timestamps import UtcTimestamp
from tests.fakes.forecast_performance_repository import FakeForecastPerformanceRepository


def _ts(hour: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, hour, tzinfo=UTC))


def _member(evaluation_key: str, outcome_key: str) -> ForecastPerformanceSnapshotMember:
    return ForecastPerformanceSnapshotMember(
        evaluation_key=evaluation_key,
        evaluation_revision_sequence=0,
        forecast_claim_key=f"{evaluation_key}-claim",
        forecast_revision_sequence=0,
        outcome_key=outcome_key,
        outcome_revision_sequence=0,
    )


def _diagnostics(
    accepted_count: int,
    excluded_by_reason: tuple[tuple[ForecastPerformanceExclusionReason, int], ...],
) -> ForecastPerformanceSampleDiagnostics:
    raw_candidate_count = accepted_count + sum(count for _, count in excluded_by_reason)
    return ForecastPerformanceSampleDiagnostics(
        raw_candidate_count=raw_candidate_count,
        accepted_count=accepted_count,
        excluded_by_reason=excluded_by_reason,
        unique_forecast_issue_count=accepted_count,
        unique_target_event_count=accepted_count,
        distinct_target_period_count=accepted_count,
        benchmark_paired_count=0,
        production_count=0,
        research_count=accepted_count,
        missing_outcome_rate=Decimal("0"),
        earliest_availability=_ts(10) if accepted_count else None,
        latest_availability=_ts(10) if accepted_count else None,
        sample_adequacy=ForecastPerformanceSampleAdequacy.INSUFFICIENT_DATA,
    )


def _snapshot(**overrides: object) -> ForecastPerformanceSnapshot:
    members: tuple[ForecastPerformanceSnapshotMember, ...] = overrides.pop(  # type: ignore[assignment]
        "members", (_member("eval-a", "outcome-a"),)
    )
    exclusions: tuple[tuple[str, ForecastPerformanceExclusionReason], ...] = overrides.pop(  # type: ignore[assignment]
        "exclusions", ()
    )
    accepted_count = len(members)
    excluded_by_reason = tuple((reason, 1) for _, reason in exclusions)
    defaults: dict[str, object] = {
        "snapshot_key": "test-snapshot",
        "revision_sequence": 0,
        "methodology_key": "test-methodology",
        "methodology_version_sequence": 0,
        "cohort_key": "test-cohort",
        "cohort_version_sequence": 0,
        "evaluation_mode": ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        "members": members,
        "exclusions": exclusions,
        "benchmark_comparison": ForecastPerformanceBenchmarkComparison(
            status=ForecastPerformanceBenchmarkComparisonStatus.BENCHMARK_UNAVAILABLE
        ),
        "diagnostics": _diagnostics(accepted_count, excluded_by_reason),
        "knowledge_cutoff": _ts(13),
        "availability": _ts(14),
        "algorithm_version": "fx66_v1",
        "numeric_summary": ForecastPerformanceNumericSummary(
            n=accepted_count,
            unit="PERCENT",
            mean_absolute_error=Decimal("0.50"),
            mean_signed_error=Decimal("-0.50"),
            root_mean_squared_error=Decimal("0.50"),
        )
        if accepted_count
        else None,
    }
    defaults.update(overrides)
    return ForecastPerformanceSnapshot(**defaults)  # type: ignore[arg-type]


async def test_first_recording_is_created() -> None:
    repo = FakeForecastPerformanceRepository()
    result = await RecordForecastPerformanceSnapshot(repo)(_snapshot())
    assert result.outcome is ForecastPerformanceSnapshotOutcome.CREATED
    assert result.snapshot.revision_sequence == 0


async def test_exact_repeat_is_unchanged() -> None:
    repo = FakeForecastPerformanceRepository()
    record = RecordForecastPerformanceSnapshot(repo)
    await record(_snapshot())
    result = await record(_snapshot(availability=_ts(20)))
    assert result.outcome is ForecastPerformanceSnapshotOutcome.UNCHANGED
    assert len(repo.snapshots["test-snapshot"]) == 1


async def test_out_of_order_availability_is_rejected() -> None:
    repo = FakeForecastPerformanceRepository()
    record = RecordForecastPerformanceSnapshot(repo)
    await record(_snapshot(availability=_ts(20)))
    with pytest.raises(OutOfOrderForecastPerformanceSnapshotError):
        await record(_snapshot(availability=_ts(5)))


async def test_different_membership_under_same_basis_raises_determinism_error() -> None:
    repo = FakeForecastPerformanceRepository()
    record = RecordForecastPerformanceSnapshot(repo)
    await record(_snapshot())
    with pytest.raises(ForecastPerformanceSnapshotDeterminismError):
        await record(
            _snapshot(
                availability=_ts(20),
                members=(_member("eval-a", "outcome-a"), _member("eval-b", "outcome-b")),
            )
        )


async def test_different_knowledge_cutoff_mints_a_new_basis_not_an_error() -> None:
    """A genuinely different knowledge_cutoff changes the BASIS, so a
    different payload is a legitimate new revision, never a
    determinism conflict (Section 16: a legitimate data change always
    mints a new, distinct basis)."""
    repo = FakeForecastPerformanceRepository()
    record = RecordForecastPerformanceSnapshot(repo)
    await record(_snapshot())
    result = await record(
        _snapshot(
            availability=_ts(20),
            knowledge_cutoff=_ts(23),
            members=(_member("eval-a", "outcome-a"), _member("eval-b", "outcome-b")),
        )
    )
    assert result.outcome is ForecastPerformanceSnapshotOutcome.REVISION_ADDED


async def test_changed_exclusions_under_same_basis_also_raises() -> None:
    repo = FakeForecastPerformanceRepository()
    record = RecordForecastPerformanceSnapshot(repo)
    await record(_snapshot())
    with pytest.raises(ForecastPerformanceSnapshotDeterminismError):
        await record(
            _snapshot(
                availability=_ts(20),
                exclusions=(("eval-z", ForecastPerformanceExclusionReason.NOT_YET_AVAILABLE),),
            )
        )


async def test_failed_determinism_check_writes_nothing_new() -> None:
    repo = FakeForecastPerformanceRepository()
    record = RecordForecastPerformanceSnapshot(repo)
    await record(_snapshot())
    with pytest.raises(ForecastPerformanceSnapshotDeterminismError):
        await record(
            _snapshot(
                availability=_ts(20),
                members=(_member("eval-a", "outcome-a"), _member("eval-b", "outcome-b")),
            )
        )
    assert len(repo.snapshots["test-snapshot"]) == 1


async def test_dry_run_does_not_persist() -> None:
    repo = FakeForecastPerformanceRepository()
    result = await RecordForecastPerformanceSnapshot(repo)(_snapshot(), dry_run=True)
    assert result.outcome is ForecastPerformanceSnapshotOutcome.CREATED
    assert "test-snapshot" not in repo.snapshots
