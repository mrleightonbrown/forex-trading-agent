"""FX-66 Section 16/20.G + FX-66H Section H3 + FX-66H.1 Section H2:
tests for `RecordForecastPerformanceSnapshot` -- full-history
determinism, idempotent exact-repeat, PIT ordering, "the same
complete basis never produces two different results," FX-66H's own
temporal integrity (a snapshot can never claim to have been recorded
before the authoritative evidence it is built from was actually
known), and FX-66H.1's own binding of the candidate's claimed payload
to what is independently derived from the authoritative population."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.application.use_cases.assess_forecast_performance_evidence import (
    AssessForecastPerformanceEvidence,
)
from forex_agent.application.use_cases.build_forecast_performance_population_as_of import (
    ForecastPerformancePopulation,
    ForecastPerformancePopulationMember,
)
from forex_agent.application.use_cases.calculate_forecast_performance import (
    CalculateForecastPerformance,
)
from forex_agent.application.use_cases.record_forecast_performance_snapshot import (
    ForecastPerformanceSnapshotConsistencyError,
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


def _consistent_snapshot(
    population: ForecastPerformancePopulation,
    *,
    snapshot_key: str = "test-snapshot",
    methodology_key: str = "test-methodology",
    methodology_version_sequence: int = 0,
    algorithm_version: str = "fx66_v1",
    availability: UtcTimestamp | None = None,
    benchmark: ForecastPerformanceBenchmarkDefinition | None = None,
    benchmark_population: ForecastPerformancePopulation | None = None,
    **overrides: object,
) -> ForecastPerformanceSnapshot:
    """Builds a snapshot whose EVERY derived field (members,
    exclusions, diagnostics, numeric/categorical summary, benchmark
    comparison) is computed from `population` via the SAME real
    `AssessForecastPerformanceEvidence`/`CalculateForecastPerformance`
    services `RecordForecastPerformanceSnapshot` itself now uses to
    validate a candidate (FX-66H.1/H2) -- so a snapshot built this way
    is, by construction, always consistent with its own population.
    Tests that need an INCONSISTENT candidate start from this and
    `dataclasses.replace` exactly the one field under test."""
    availability = availability or _ts(14)
    numeric_summary, categorical_summary, comparison = CalculateForecastPerformance()(
        population, benchmark=benchmark, benchmark_population=benchmark_population
    )
    diagnostics = AssessForecastPerformanceEvidence()(
        population, benchmark_paired_count=comparison.paired_count
    )
    members = tuple(
        ForecastPerformanceSnapshotMember(
            evaluation_key=m.evaluation.evaluation_key,
            evaluation_revision_sequence=m.evaluation.revision_sequence,
            forecast_claim_key=m.evaluation.forecast_claim_key,
            forecast_revision_sequence=m.evaluation.forecast_revision_sequence,
            outcome_key=m.evaluation.outcome_key,
            outcome_revision_sequence=m.evaluation.outcome_revision_sequence,
        )
        for m in population.accepted
    )
    defaults: dict[str, object] = {
        "snapshot_key": snapshot_key,
        "revision_sequence": 0,
        "methodology_key": methodology_key,
        "methodology_version_sequence": methodology_version_sequence,
        "cohort_key": population.cohort.cohort_key,
        "cohort_version_sequence": population.cohort.version_sequence,
        "evaluation_mode": population.cohort.evaluation_mode,
        "members": members,
        "exclusions": population.exclusions,
        "benchmark_comparison": comparison,
        "diagnostics": diagnostics,
        "knowledge_cutoff": population.knowledge_cutoff,
        "availability": availability,
        "algorithm_version": algorithm_version,
        "numeric_summary": numeric_summary,
        "categorical_summary": categorical_summary,
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
    benchmark_population: ForecastPerformancePopulation | None = None,
    dry_run: bool = False,
) -> ForecastPerformanceSnapshotRecordResult:
    return await RecordForecastPerformanceSnapshot(repo)(
        snapshot,
        population=population or _population(),
        methodology=methodology or _methodology(),
        benchmark=benchmark,
        benchmark_population=benchmark_population,
        dry_run=dry_run,
    )


# --- existing determinism/idempotency/PIT-ordering coverage ---------------


async def test_first_recording_is_created() -> None:
    repo = FakeForecastPerformanceRepository()
    population = _population()
    result = await _record(repo, _consistent_snapshot(population), population=population)
    assert result.outcome is ForecastPerformanceSnapshotOutcome.CREATED
    assert result.snapshot.revision_sequence == 0


async def test_exact_repeat_is_unchanged() -> None:
    repo = FakeForecastPerformanceRepository()
    population = _population()
    await _record(repo, _consistent_snapshot(population), population=population)
    result = await _record(
        repo, _consistent_snapshot(population, availability=_ts(20)), population=population
    )
    assert result.outcome is ForecastPerformanceSnapshotOutcome.UNCHANGED
    assert len(repo.snapshots["test-snapshot"]) == 1


async def test_out_of_order_availability_is_rejected() -> None:
    repo = FakeForecastPerformanceRepository()
    population = _population()
    await _record(
        repo, _consistent_snapshot(population, availability=_ts(20)), population=population
    )
    with pytest.raises(OutOfOrderForecastPerformanceSnapshotError):
        await _record(
            repo, _consistent_snapshot(population, availability=_ts(15)), population=population
        )


async def test_different_membership_under_same_basis_raises_determinism_error() -> None:
    repo = FakeForecastPerformanceRepository()
    population_a = _population()
    await _record(repo, _consistent_snapshot(population_a), population=population_a)

    population_b = _population(
        members=(
            _population_member("eval-a", "outcome-a", evaluation_availability=_ts(10)),
            _population_member("eval-b", "outcome-b", evaluation_availability=_ts(10)),
        )
    )
    with pytest.raises(ForecastPerformanceSnapshotDeterminismError):
        await _record(
            repo,
            _consistent_snapshot(population_b, availability=_ts(20)),
            population=population_b,
        )


async def test_different_knowledge_cutoff_mints_a_new_basis_not_an_error() -> None:
    """A genuinely different knowledge_cutoff changes the BASIS, so a
    different payload is a legitimate new revision, never a
    determinism conflict (Section 16: a legitimate data change always
    mints a new, distinct basis)."""
    repo = FakeForecastPerformanceRepository()
    population_a = _population()
    await _record(repo, _consistent_snapshot(population_a), population=population_a)

    population_b = _population(
        members=(
            _population_member("eval-a", "outcome-a", evaluation_availability=_ts(10)),
            _population_member("eval-b", "outcome-b", evaluation_availability=_ts(10)),
        ),
        knowledge_cutoff=_ts(23),
    )
    result = await _record(
        repo,
        _consistent_snapshot(population_b, availability=_ts(23)),
        population=population_b,
    )
    assert result.outcome is ForecastPerformanceSnapshotOutcome.REVISION_ADDED


async def test_changed_exclusions_under_same_basis_also_raises() -> None:
    repo = FakeForecastPerformanceRepository()
    population_a = _population()
    await _record(repo, _consistent_snapshot(population_a), population=population_a)

    population_b = _population(
        exclusions=(("eval-z", ForecastPerformanceExclusionReason.KNOWN_DUPLICATE_SYNDICATED),)
    )
    with pytest.raises(ForecastPerformanceSnapshotDeterminismError):
        await _record(
            repo,
            _consistent_snapshot(population_b, availability=_ts(20)),
            population=population_b,
        )


async def test_failed_determinism_check_writes_nothing_new() -> None:
    repo = FakeForecastPerformanceRepository()
    population_a = _population()
    await _record(repo, _consistent_snapshot(population_a), population=population_a)

    population_b = _population(
        members=(
            _population_member("eval-a", "outcome-a", evaluation_availability=_ts(10)),
            _population_member("eval-b", "outcome-b", evaluation_availability=_ts(10)),
        )
    )
    with pytest.raises(ForecastPerformanceSnapshotDeterminismError):
        await _record(
            repo,
            _consistent_snapshot(population_b, availability=_ts(20)),
            population=population_b,
        )
    assert len(repo.snapshots["test-snapshot"]) == 1


async def test_dry_run_does_not_persist() -> None:
    repo = FakeForecastPerformanceRepository()
    population = _population()
    result = await _record(
        repo, _consistent_snapshot(population), population=population, dry_run=True
    )
    assert result.outcome is ForecastPerformanceSnapshotOutcome.CREATED
    assert "test-snapshot" not in repo.snapshots


# --- FX-66H (H3): snapshot temporal integrity ------------------------------


async def test_h3_snapshot_after_all_required_inputs_is_accepted() -> None:
    repo = FakeForecastPerformanceRepository()
    population = _population()
    result = await _record(
        repo, _consistent_snapshot(population, availability=_ts(14)), population=population
    )
    assert result.outcome is ForecastPerformanceSnapshotOutcome.CREATED


async def test_h3_snapshot_predating_cohort_definition_is_rejected() -> None:
    repo = FakeForecastPerformanceRepository()
    cohort = _cohort(availability=_ts(20))
    population = _population(cohort=cohort)
    with pytest.raises(ForecastPerformanceSnapshotTemporalIntegrityError):
        await _record(
            repo, _consistent_snapshot(population, availability=_ts(14)), population=population
        )


async def test_h3_snapshot_predating_methodology_definition_is_rejected() -> None:
    repo = FakeForecastPerformanceRepository()
    methodology = _methodology(availability=_ts(20))
    population = _population()
    with pytest.raises(ForecastPerformanceSnapshotTemporalIntegrityError):
        await _record(
            repo,
            _consistent_snapshot(population, availability=_ts(14)),
            methodology=methodology,
            population=population,
        )


async def test_h3_snapshot_predating_benchmark_version_is_rejected() -> None:
    repo = FakeForecastPerformanceRepository()
    benchmark = _benchmark(availability=_ts(20))
    population = _population()
    snapshot = _consistent_snapshot(population, availability=_ts(14), benchmark=benchmark)
    with pytest.raises(ForecastPerformanceSnapshotTemporalIntegrityError):
        await _record(repo, snapshot, benchmark=benchmark, population=population)


async def test_h3_snapshot_predating_selected_evaluation_vintage_is_rejected() -> None:
    repo = FakeForecastPerformanceRepository()
    population = _population(
        members=(_population_member("eval-a", "outcome-a", evaluation_availability=_ts(20)),)
    )
    with pytest.raises(ForecastPerformanceSnapshotTemporalIntegrityError):
        await _record(
            repo, _consistent_snapshot(population, availability=_ts(14)), population=population
        )


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
        await _record(
            repo, _consistent_snapshot(population, availability=_ts(14)), population=population
        )


async def test_h3_rejected_snapshot_produces_no_write() -> None:
    repo = FakeForecastPerformanceRepository()
    cohort = _cohort(availability=_ts(20))
    population = _population(cohort=cohort)
    with pytest.raises(ForecastPerformanceSnapshotTemporalIntegrityError):
        await _record(
            repo, _consistent_snapshot(population, availability=_ts(14)), population=population
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
        repo, _consistent_snapshot(population, availability=_ts(14)), population=population
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
    population = _population()
    mismatched_population = _population(cohort=_cohort(cohort_key="a-different-cohort"))
    with pytest.raises(ForecastPerformanceSnapshotIdentityMismatchError):
        await _record(repo, _consistent_snapshot(population), population=mismatched_population)


async def test_h3_later_evaluation_correction_does_not_mutate_earlier_persisted_snapshot() -> None:
    """A later evaluation correction, surfaced as a DIFFERENT payload
    under the SAME basis, is refused by the determinism check -- and
    the ALREADY-persisted snapshot must remain byte-identical to what
    was first recorded, never silently mutated (FX-66H.1's own H2
    requirement, mirroring FX-66H's own H3)."""
    repo = FakeForecastPerformanceRepository()
    population_a = _population()
    original_result = await _record(
        repo, _consistent_snapshot(population_a), population=population_a
    )
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
            _consistent_snapshot(corrected_population, availability=_ts(20)),
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
    snapshot = _consistent_snapshot(production_population)
    await _record(repo, snapshot, population=production_population)

    research_read = await repo.latest_snapshot_as_of_for_research("test-snapshot", _ts(20))
    production_read = await repo.latest_production_observed_snapshot_as_of("test-snapshot", _ts(20))

    assert research_read is not None  # research reads see EITHER mode
    assert production_read is not None
    assert production_read.evaluation_mode is ForecastProvenanceMode.PRODUCTION_OBSERVED


# --- FX-66H.1 (H2/F66-05): binding the payload to the authoritative population


async def test_h2_valid_complete_snapshot_with_benchmark_is_accepted() -> None:
    repo = FakeForecastPerformanceRepository()
    benchmark = _benchmark()
    population = _population(
        members=(
            _population_member("eval-a", "outcome-a", evaluation_availability=_ts(10)),
            _population_member("eval-b", "outcome-b", evaluation_availability=_ts(10)),
        )
    )
    snapshot = _consistent_snapshot(population, benchmark=benchmark)
    result = await _record(repo, snapshot, population=population, benchmark=benchmark)
    assert result.outcome is ForecastPerformanceSnapshotOutcome.CREATED


async def test_h2_missing_accepted_member_rejected() -> None:
    """A member swapped for one not in the population at all --
    domain-level cardinality (`len(members) == diagnostics.accepted_
    count`) still holds, but content no longer matches."""
    repo = FakeForecastPerformanceRepository()
    population = _population(
        members=(
            _population_member("eval-a", "outcome-a", evaluation_availability=_ts(10)),
            _population_member("eval-b", "outcome-b", evaluation_availability=_ts(10)),
        )
    )
    snapshot = _consistent_snapshot(population)
    tampered = replace(snapshot, members=(snapshot.members[0], _member("eval-z", "outcome-z")))
    with pytest.raises(ForecastPerformanceSnapshotConsistencyError) as exc_info:
        await _record(repo, tampered, population=population)
    assert "members" in exc_info.value.mismatched_fields


async def test_h2_extra_member_rejected() -> None:
    repo = FakeForecastPerformanceRepository()
    small_population = _population()
    larger_population = _population(
        members=(
            _population_member("eval-a", "outcome-a", evaluation_availability=_ts(10)),
            _population_member("eval-b", "outcome-b", evaluation_availability=_ts(10)),
        )
    )
    padded_snapshot = _consistent_snapshot(larger_population)
    with pytest.raises(ForecastPerformanceSnapshotConsistencyError) as exc_info:
        await _record(repo, padded_snapshot, population=small_population)
    assert "members" in exc_info.value.mismatched_fields


async def test_h2_modified_mae_rejected() -> None:
    repo = FakeForecastPerformanceRepository()
    population = _population()
    snapshot = _consistent_snapshot(population)
    assert snapshot.numeric_summary is not None
    tampered = replace(
        snapshot,
        numeric_summary=replace(snapshot.numeric_summary, mean_absolute_error=Decimal("99.99")),
    )
    with pytest.raises(ForecastPerformanceSnapshotConsistencyError) as exc_info:
        await _record(repo, tampered, population=population)
    assert "numeric_summary" in exc_info.value.mismatched_fields


async def test_h2_modified_signed_mean_error_rejected() -> None:
    repo = FakeForecastPerformanceRepository()
    population = _population()
    snapshot = _consistent_snapshot(population)
    assert snapshot.numeric_summary is not None
    tampered = replace(
        snapshot,
        numeric_summary=replace(snapshot.numeric_summary, mean_signed_error=Decimal("-99.99")),
    )
    with pytest.raises(ForecastPerformanceSnapshotConsistencyError) as exc_info:
        await _record(repo, tampered, population=population)
    assert "numeric_summary" in exc_info.value.mismatched_fields


async def test_h2_modified_diagnostic_count_rejected() -> None:
    repo = FakeForecastPerformanceRepository()
    population = _population()
    snapshot = _consistent_snapshot(population)
    tampered = replace(
        snapshot, diagnostics=replace(snapshot.diagnostics, unique_forecast_issue_count=999)
    )
    with pytest.raises(ForecastPerformanceSnapshotConsistencyError) as exc_info:
        await _record(repo, tampered, population=population)
    assert "diagnostics" in exc_info.value.mismatched_fields


async def test_h2_different_knowledge_cutoff_rejected() -> None:
    repo = FakeForecastPerformanceRepository()
    population = _population()
    snapshot = _consistent_snapshot(population)
    tampered = replace(snapshot, knowledge_cutoff=_ts(5, day=9))
    with pytest.raises(ForecastPerformanceSnapshotIdentityMismatchError) as exc_info:
        await _record(repo, tampered, population=population)
    assert exc_info.value.field == "knowledge_cutoff"


async def test_h2_changed_evaluation_mode_rejected() -> None:
    repo = FakeForecastPerformanceRepository()
    population = _population()
    snapshot = _consistent_snapshot(population)
    tampered = replace(snapshot, evaluation_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED)
    with pytest.raises(ForecastPerformanceSnapshotIdentityMismatchError) as exc_info:
        await _record(repo, tampered, population=population)
    assert exc_info.value.field == "evaluation_mode"


async def test_h2_wrong_benchmark_result_rejected() -> None:
    repo = FakeForecastPerformanceRepository()
    benchmark = _benchmark()
    population = _population()
    snapshot = _consistent_snapshot(population, benchmark=benchmark)
    assert (
        snapshot.benchmark_comparison.status
        is ForecastPerformanceBenchmarkComparisonStatus.COMPARED
    )
    tampered = replace(
        snapshot,
        benchmark_comparison=replace(
            snapshot.benchmark_comparison, benchmark_mean_absolute_error=Decimal("0.01")
        ),
    )
    with pytest.raises(ForecastPerformanceSnapshotConsistencyError) as exc_info:
        await _record(repo, tampered, benchmark=benchmark, population=population)
    assert "benchmark_comparison" in exc_info.value.mismatched_fields


async def test_h2_valid_identical_rerun_remains_unchanged() -> None:
    repo = FakeForecastPerformanceRepository()
    population = _population()
    await _record(repo, _consistent_snapshot(population), population=population)
    result = await _record(
        repo, _consistent_snapshot(population, availability=_ts(20)), population=population
    )
    assert result.outcome is ForecastPerformanceSnapshotOutcome.UNCHANGED


async def test_h2_rejected_recording_leaves_no_partial_write() -> None:
    repo = FakeForecastPerformanceRepository()
    population = _population()
    snapshot = _consistent_snapshot(population)
    assert snapshot.numeric_summary is not None
    tampered = replace(
        snapshot,
        numeric_summary=replace(snapshot.numeric_summary, mean_absolute_error=Decimal("99.99")),
    )
    with pytest.raises(ForecastPerformanceSnapshotConsistencyError):
        await _record(repo, tampered, population=population)
    assert "test-snapshot" not in repo.snapshots
