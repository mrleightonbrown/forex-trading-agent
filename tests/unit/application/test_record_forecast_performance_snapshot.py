"""FX-66 Section 16/20.G + FX-66H Section H3: tests for `RecordForecast
PerformanceSnapshot` -- full-history determinism, idempotent exact-
repeat, PIT ordering, "the same complete basis never produces two
different results," and (FX-66H) temporal integrity: a snapshot can
never claim to have been recorded before the authoritative evidence
it is built from was actually known."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.application.use_cases.build_forecast_performance_population_as_of import (
    ForecastPerformancePopulation,
    ForecastPerformancePopulationMember,
)
from forex_agent.application.use_cases.record_forecast_performance_snapshot import (
    ForecastPerformanceSnapshotDeterminismError,
    ForecastPerformanceSnapshotIdentityMismatchError,
    ForecastPerformanceSnapshotOutcome,
    ForecastPerformanceSnapshotRecordResult,
    ForecastPerformanceSnapshotTemporalIntegrityError,
    OutOfOrderForecastPerformanceSnapshotError,
    RecordForecastPerformanceSnapshot,
)
from forex_agent.domain.evidence_authentication_review import EvidenceAuthenticationReview
from forex_agent.domain.forecast_attribution import ForecastAttribution
from forex_agent.domain.forecast_attribution_kind import ForecastAttributionKind
from forex_agent.domain.forecast_evaluation_metric import ForecastEvaluationMetric
from forex_agent.domain.forecast_evaluation_result import ForecastEvaluationResult
from forex_agent.domain.forecast_evidence_kind import ForecastEvidenceKind
from forex_agent.domain.forecast_evidence_reference import ForecastEvidenceReference
from forex_agent.domain.forecast_outcome_vintage import ForecastOutcomeVintage
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
from forex_agent.domain.forecast_target_period import ForecastTargetPeriod
from forex_agent.domain.forecast_target_period_kind import ForecastTargetPeriodKind
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.structured_forecast_evaluation_vintage import (
    StructuredForecastEvaluationVintage,
)
from forex_agent.domain.structured_forecast_vintage import StructuredForecastVintage
from forex_agent.domain.timestamps import UtcTimestamp
from tests.fakes.forecast_performance_repository import FakeForecastPerformanceRepository

_PUBLISHER = "test-publisher"


def _ts(hour: int, day: int = 1) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, day, hour, tzinfo=UTC))


def _review(reviewed_at: UtcTimestamp) -> EvidenceAuthenticationReview:
    return EvidenceAuthenticationReview(
        reviewed_by="tester", review_method="synthetic", reviewed_at=reviewed_at
    )


def _population_member(
    evaluation_key: str,
    outcome_key: str,
    *,
    evaluation_availability: UtcTimestamp,
    forecast_review_at: UtcTimestamp | None = None,
    outcome_review_at: UtcTimestamp | None = None,
) -> ForecastPerformancePopulationMember:
    forecast_review_at = forecast_review_at or evaluation_availability
    outcome_review_at = outcome_review_at or evaluation_availability
    period = ForecastTargetPeriod(
        period_kind=ForecastTargetPeriodKind.POLICY_MEETING, policy_meeting_identifier="M1"
    )
    evidence = ForecastEvidenceReference(
        evidence_kind=ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
        description="test",
        document_identifier=f"{evaluation_key}-doc",
    )
    forecast_vintage = StructuredForecastVintage(
        claim_key=f"{evaluation_key}-claim",
        revision_sequence=0,
        availability=evaluation_availability,
        algorithm_version="test_v1",
        forecast_type=ForecastType.NUMERIC_POINT,
        target_key="CA_POLICY_RATE_LEVEL_AFTER_MEETING",
        target_period=period,
        attribution=ForecastAttribution(
            kind=ForecastAttributionKind.AGGREGATE_SURVEY_CONSENSUS,
            publisher_source_key=_PUBLISHER,
        ),
        provenance_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        evidence=evidence,
        numeric_value=Decimal("3.75"),
        unit="PERCENT",
    )
    outcome_vintage = ForecastOutcomeVintage(
        outcome_key=outcome_key,
        revision_sequence=0,
        definition_key="test-def",
        definition_version_sequence=0,
        availability=evaluation_availability,
        target_period=period,
        outcome_type=ForecastType.NUMERIC_POINT,
        evidence=evidence,
        authentication_review=_review(outcome_review_at),
        provenance_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        numeric_value=Decimal("3.25"),
        unit="PERCENT",
    )
    evaluation = StructuredForecastEvaluationVintage(
        evaluation_key=evaluation_key,
        revision_sequence=0,
        forecast_claim_key=forecast_vintage.claim_key,
        forecast_revision_sequence=0,
        protocol_key="test-protocol",
        protocol_version_sequence=0,
        outcome_definition_key="test-def",
        outcome_definition_version_sequence=0,
        outcome_key=outcome_key,
        outcome_revision_sequence=0,
        evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        algorithm_version="fx65_v1",
        availability=evaluation_availability,
        result=ForecastEvaluationResult(
            metric=ForecastEvaluationMetric.NUMERIC_ERROR,
            signed_error=Decimal("-0.50"),
            absolute_error=Decimal("0.50"),
            unit="PERCENT",
        ),
        forecast_authentication_review=_review(forecast_review_at),
    )
    return ForecastPerformancePopulationMember(evaluation, forecast_vintage, outcome_vintage)


def _cohort(**overrides: object) -> ForecastPerformanceCohortDefinition:
    defaults: dict[str, object] = {
        "cohort_key": "test-cohort",
        "version_sequence": 0,
        "attribution_kind": ForecastAttributionKind.AGGREGATE_SURVEY_CONSENSUS,
        "originator_publisher_source_key": _PUBLISHER,
        "target_key": "CA_POLICY_RATE_LEVEL_AFTER_MEETING",
        "forecast_type": ForecastType.NUMERIC_POINT,
        "horizon_category": "SAME-MEETING",
        "protocol_key": "test-protocol",
        "protocol_version_sequence": 0,
        "evaluation_mode": ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        "duplicate_selection_policy": (
            ForecastPerformanceDuplicateSelectionPolicy.EARLIEST_QUALIFYING_ISSUE
        ),
        "availability": _ts(1),
        "rationale": "test cohort",
    }
    defaults.update(overrides)
    return ForecastPerformanceCohortDefinition(**defaults)  # type: ignore[arg-type]


def _methodology(**overrides: object) -> ForecastPerformanceMethodology:
    defaults: dict[str, object] = {
        "methodology_key": "test-methodology",
        "version_sequence": 0,
        "cohort_key": "test-cohort",
        "cohort_version_sequence": 0,
        "missing_data_policy": ForecastPerformanceMissingDataPolicy.EXCLUDE_FROM_DENOMINATOR,
        "algorithm_version": "fx66_v1",
        "availability": _ts(1),
        "rationale": "test methodology",
    }
    defaults.update(overrides)
    return ForecastPerformanceMethodology(**defaults)  # type: ignore[arg-type]


def _benchmark(**overrides: object) -> ForecastPerformanceBenchmarkDefinition:
    defaults: dict[str, object] = {
        "benchmark_key": "test-benchmark",
        "version_sequence": 0,
        "kind": ForecastPerformanceBenchmarkKind.NAIVE_NUMERIC,
        "target_key": "CA_POLICY_RATE_LEVEL_AFTER_MEETING",
        "horizon_category": "SAME-MEETING",
        "metric": ForecastEvaluationMetric.NUMERIC_ERROR,
        "availability": _ts(1),
        "rationale": "test benchmark",
        "naive_numeric_reference_value": Decimal("3.5"),
        "naive_numeric_reference_description": "fixed reference",
    }
    defaults.update(overrides)
    return ForecastPerformanceBenchmarkDefinition(**defaults)  # type: ignore[arg-type]


def _population(
    *,
    cohort: ForecastPerformanceCohortDefinition | None = None,
    members: tuple[ForecastPerformancePopulationMember, ...] | None = None,
    exclusions: tuple[tuple[str, ForecastPerformanceExclusionReason], ...] = (),
    knowledge_cutoff: UtcTimestamp | None = None,
    raw_candidate_count: int | None = None,
) -> ForecastPerformancePopulation:
    cohort = cohort or _cohort()
    members = (
        members
        if members is not None
        else (_population_member("eval-a", "outcome-a", evaluation_availability=_ts(10)),)
    )
    return ForecastPerformancePopulation(
        cohort=cohort,
        knowledge_cutoff=knowledge_cutoff or _ts(13),
        raw_candidate_count=(
            raw_candidate_count
            if raw_candidate_count is not None
            else len(members) + len(exclusions)
        ),
        accepted=members,
        exclusions=exclusions,
    )


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
        "numeric_summary": (
            ForecastPerformanceNumericSummary(
                n=accepted_count,
                unit="PERCENT",
                mean_absolute_error=Decimal("0.50"),
                mean_signed_error=Decimal("-0.50"),
                root_mean_squared_error=Decimal("0.50"),
            )
            if accepted_count
            else None
        ),
    }
    defaults.update(overrides)
    return ForecastPerformanceSnapshot(**defaults)  # type: ignore[arg-type]


async def _record(
    repo: FakeForecastPerformanceRepository,
    snapshot: ForecastPerformanceSnapshot,
    *,
    population: ForecastPerformancePopulation | None = None,
    methodology: ForecastPerformanceMethodology | None = None,
    benchmark: ForecastPerformanceBenchmarkDefinition | None = None,
    dry_run: bool = False,
) -> ForecastPerformanceSnapshotRecordResult:
    return await RecordForecastPerformanceSnapshot(repo)(
        snapshot,
        population=population or _population(),
        methodology=methodology or _methodology(),
        benchmark=benchmark,
        dry_run=dry_run,
    )


# --- existing determinism/idempotency/PIT-ordering coverage ---------------


async def test_first_recording_is_created() -> None:
    repo = FakeForecastPerformanceRepository()
    result = await _record(repo, _snapshot())
    assert result.outcome is ForecastPerformanceSnapshotOutcome.CREATED
    assert result.snapshot.revision_sequence == 0


async def test_exact_repeat_is_unchanged() -> None:
    repo = FakeForecastPerformanceRepository()
    await _record(repo, _snapshot())
    result = await _record(repo, _snapshot(availability=_ts(20)))
    assert result.outcome is ForecastPerformanceSnapshotOutcome.UNCHANGED
    assert len(repo.snapshots["test-snapshot"]) == 1


async def test_out_of_order_availability_is_rejected() -> None:
    repo = FakeForecastPerformanceRepository()
    await _record(repo, _snapshot(availability=_ts(20)))
    with pytest.raises(OutOfOrderForecastPerformanceSnapshotError):
        await _record(repo, _snapshot(availability=_ts(15)))


async def test_different_membership_under_same_basis_raises_determinism_error() -> None:
    repo = FakeForecastPerformanceRepository()
    await _record(repo, _snapshot())
    population = _population(
        members=(
            _population_member("eval-a", "outcome-a", evaluation_availability=_ts(10)),
            _population_member("eval-b", "outcome-b", evaluation_availability=_ts(10)),
        )
    )
    with pytest.raises(ForecastPerformanceSnapshotDeterminismError):
        await _record(
            repo,
            _snapshot(
                availability=_ts(20),
                members=(_member("eval-a", "outcome-a"), _member("eval-b", "outcome-b")),
            ),
            population=population,
        )


async def test_different_knowledge_cutoff_mints_a_new_basis_not_an_error() -> None:
    """A genuinely different knowledge_cutoff changes the BASIS, so a
    different payload is a legitimate new revision, never a
    determinism conflict (Section 16: a legitimate data change always
    mints a new, distinct basis)."""
    repo = FakeForecastPerformanceRepository()
    await _record(repo, _snapshot())
    population = _population(
        members=(
            _population_member("eval-a", "outcome-a", evaluation_availability=_ts(10)),
            _population_member("eval-b", "outcome-b", evaluation_availability=_ts(10)),
        ),
        knowledge_cutoff=_ts(23),
    )
    result = await _record(
        repo,
        _snapshot(
            availability=_ts(23),
            knowledge_cutoff=_ts(23),
            members=(_member("eval-a", "outcome-a"), _member("eval-b", "outcome-b")),
        ),
        population=population,
    )
    assert result.outcome is ForecastPerformanceSnapshotOutcome.REVISION_ADDED


async def test_changed_exclusions_under_same_basis_also_raises() -> None:
    repo = FakeForecastPerformanceRepository()
    await _record(repo, _snapshot())
    with pytest.raises(ForecastPerformanceSnapshotDeterminismError):
        await _record(
            repo,
            _snapshot(
                availability=_ts(20),
                exclusions=(("eval-z", ForecastPerformanceExclusionReason.NOT_YET_AVAILABLE),),
            ),
        )


async def test_failed_determinism_check_writes_nothing_new() -> None:
    repo = FakeForecastPerformanceRepository()
    await _record(repo, _snapshot())
    population = _population(
        members=(
            _population_member("eval-a", "outcome-a", evaluation_availability=_ts(10)),
            _population_member("eval-b", "outcome-b", evaluation_availability=_ts(10)),
        )
    )
    with pytest.raises(ForecastPerformanceSnapshotDeterminismError):
        await _record(
            repo,
            _snapshot(
                availability=_ts(20),
                members=(_member("eval-a", "outcome-a"), _member("eval-b", "outcome-b")),
            ),
            population=population,
        )
    assert len(repo.snapshots["test-snapshot"]) == 1


async def test_dry_run_does_not_persist() -> None:
    repo = FakeForecastPerformanceRepository()
    result = await _record(repo, _snapshot(), dry_run=True)
    assert result.outcome is ForecastPerformanceSnapshotOutcome.CREATED
    assert "test-snapshot" not in repo.snapshots


# --- FX-66H (H3): snapshot temporal integrity ------------------------------


async def test_h3_snapshot_after_all_required_inputs_is_accepted() -> None:
    repo = FakeForecastPerformanceRepository()
    result = await _record(repo, _snapshot(availability=_ts(14)))
    assert result.outcome is ForecastPerformanceSnapshotOutcome.CREATED


async def test_h3_snapshot_predating_cohort_definition_is_rejected() -> None:
    repo = FakeForecastPerformanceRepository()
    cohort = _cohort(availability=_ts(20))
    population = _population(cohort=cohort)
    with pytest.raises(ForecastPerformanceSnapshotTemporalIntegrityError):
        await _record(
            repo,
            _snapshot(availability=_ts(14), cohort_key=cohort.cohort_key),
            population=population,
        )


async def test_h3_snapshot_predating_methodology_definition_is_rejected() -> None:
    repo = FakeForecastPerformanceRepository()
    methodology = _methodology(availability=_ts(20))
    with pytest.raises(ForecastPerformanceSnapshotTemporalIntegrityError):
        await _record(repo, _snapshot(availability=_ts(14)), methodology=methodology)


async def test_h3_snapshot_predating_benchmark_version_is_rejected() -> None:
    repo = FakeForecastPerformanceRepository()
    benchmark = _benchmark(availability=_ts(20))
    snapshot = _snapshot(
        availability=_ts(14),
        benchmark_comparison=ForecastPerformanceBenchmarkComparison(
            status=ForecastPerformanceBenchmarkComparisonStatus.COMPARED,
            benchmark_key=benchmark.benchmark_key,
            benchmark_version_sequence=benchmark.version_sequence,
            paired_count=1,
            source_mean_absolute_error=Decimal("0.5"),
            benchmark_mean_absolute_error=Decimal("0.6"),
            mean_absolute_error_difference=Decimal("-0.1"),
            relative_mae_improvement=Decimal("0.1"),
        ),
    )
    with pytest.raises(ForecastPerformanceSnapshotTemporalIntegrityError):
        await _record(repo, snapshot, benchmark=benchmark)


async def test_h3_snapshot_predating_selected_evaluation_vintage_is_rejected() -> None:
    repo = FakeForecastPerformanceRepository()
    population = _population(
        members=(_population_member("eval-a", "outcome-a", evaluation_availability=_ts(20)),)
    )
    with pytest.raises(ForecastPerformanceSnapshotTemporalIntegrityError):
        await _record(repo, _snapshot(availability=_ts(14)), population=population)


async def test_h3_snapshot_predating_authentication_review_is_rejected() -> None:
    repo = FakeForecastPerformanceRepository()
    population = _population(
        members=(
            _population_member(
                "eval-a",
                "outcome-a",
                evaluation_availability=_ts(10),
                forecast_review_at=_ts(20),
            ),
        )
    )
    with pytest.raises(ForecastPerformanceSnapshotTemporalIntegrityError):
        await _record(repo, _snapshot(availability=_ts(14)), population=population)


async def test_h3_rejected_snapshot_produces_no_write() -> None:
    repo = FakeForecastPerformanceRepository()
    cohort = _cohort(availability=_ts(20))
    population = _population(cohort=cohort)
    with pytest.raises(ForecastPerformanceSnapshotTemporalIntegrityError):
        await _record(
            repo,
            _snapshot(availability=_ts(14), cohort_key=cohort.cohort_key),
            population=population,
        )
    assert "test-snapshot" not in repo.snapshots


async def test_h3_historical_cutoff_valid_only_visible_after_actual_recording() -> None:
    """A snapshot recorded TODAY analyzing a historical knowledge
    cutoff is valid (availability is NOT backdated to the cutoff) --
    but it is only visible via PIT reads once its OWN availability
    has actually passed."""
    repo = FakeForecastPerformanceRepository()
    population = _population(knowledge_cutoff=_ts(5))
    result = await _record(
        repo, _snapshot(availability=_ts(14), knowledge_cutoff=_ts(5)), population=population
    )
    assert result.outcome is ForecastPerformanceSnapshotOutcome.CREATED

    visible_too_early = await repo.latest_snapshot_as_of_for_research(
        "test-snapshot", research_as_of=_ts(10)
    )
    assert visible_too_early is None
    visible_now = await repo.latest_snapshot_as_of_for_research(
        "test-snapshot", research_as_of=_ts(14)
    )
    assert visible_now is not None


async def test_h3_identity_mismatch_between_candidate_and_population_cohort_is_rejected() -> None:
    repo = FakeForecastPerformanceRepository()
    mismatched_population = _population(cohort=_cohort(cohort_key="a-different-cohort"))
    with pytest.raises(ForecastPerformanceSnapshotIdentityMismatchError):
        await _record(repo, _snapshot(), population=mismatched_population)


async def test_h3_later_evaluation_correction_does_not_mutate_earlier_persisted_snapshot() -> None:
    """A later evaluation correction, surfaced as a DIFFERENT payload
    under the SAME basis, is refused by the determinism check -- and
    the ALREADY-persisted snapshot must remain byte-identical to what
    was first recorded, never silently mutated."""
    repo = FakeForecastPerformanceRepository()
    original_result = await _record(repo, _snapshot())
    original_snapshot = original_result.snapshot

    corrected_population = _population(
        members=(
            _population_member("eval-a", "outcome-a", evaluation_availability=_ts(10)),
            _population_member("eval-b", "outcome-b", evaluation_availability=_ts(10)),
        )
    )
    with pytest.raises(ForecastPerformanceSnapshotDeterminismError):
        await _record(
            repo,
            _snapshot(
                availability=_ts(20),
                members=(_member("eval-a", "outcome-a"), _member("eval-b", "outcome-b")),
            ),
            population=corrected_population,
        )

    persisted = await repo.latest_snapshot_vintage("test-snapshot")
    assert persisted == original_snapshot


async def test_h3_production_and_retrospective_snapshot_visibility_remain_distinct() -> None:
    repo = FakeForecastPerformanceRepository()
    production_population = _population(
        cohort=_cohort(evaluation_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED),
        members=(_population_member("eval-a", "outcome-a", evaluation_availability=_ts(10)),),
    )
    snapshot = _snapshot(evaluation_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED)
    await _record(repo, snapshot, population=production_population)

    research_read = await repo.latest_snapshot_as_of_for_research("test-snapshot", _ts(20))
    production_read = await repo.latest_production_observed_snapshot_as_of("test-snapshot", _ts(20))

    assert research_read is not None  # research reads see EITHER mode
    assert production_read is not None
    assert production_read.evaluation_mode is ForecastProvenanceMode.PRODUCTION_OBSERVED
