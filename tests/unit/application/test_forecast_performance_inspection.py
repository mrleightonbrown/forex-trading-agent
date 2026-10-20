"""FX-67 Section 19/20.A-F: synthetic-fixture tests for the read-only
forecast-performance inspection use cases -- all data here is
SYNTHETIC and labelled as such (mirrors `test_forecast_performance_
pipeline.py`'s own "synthetic, never real" discipline); see `tests/
integration/test_forecast_performance_inspection.py` for the one
real-data demonstration and the real-Postgres sections."""

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
from forex_agent.application.use_cases.forecast_performance_inspection_support import (
    InvalidInspectionPageBoundsError,
    UnresolvedEvidenceReference,
)
from forex_agent.application.use_cases.get_forecast_evaluation_inspection import (
    ForecastEvaluationInspection,
    GetForecastEvaluationInspection,
)
from forex_agent.application.use_cases.get_forecast_performance_benchmark_inspection import (
    GetForecastPerformanceBenchmarkInspection,
)
from forex_agent.application.use_cases.get_forecast_performance_exclusions import (
    GetForecastPerformanceExclusions,
)
from forex_agent.application.use_cases.get_forecast_performance_inspection import (
    GetForecastPerformanceInspection,
    SnapshotNotVisibleForInspectionError,
)
from forex_agent.application.use_cases.get_forecast_performance_limitations import (
    HORIZON_LIMITATION,
    GetForecastPerformanceLimitations,
)
from forex_agent.application.use_cases.get_forecast_performance_members import (
    GetForecastPerformanceMembers,
)
from forex_agent.application.use_cases.list_forecast_performance_snapshots import (
    ListForecastPerformanceSnapshots,
)
from forex_agent.application.use_cases.record_source_identity_vintage import (
    RecordSourceIdentityVintage,
)
from forex_agent.domain.categorical_evaluation_result import CategoricalEvaluationResult
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
from forex_agent.domain.forecast_performance_inspection_mode import (
    ForecastPerformanceInspectionMode,
)
from forex_agent.domain.forecast_performance_methodology import ForecastPerformanceMethodology
from forex_agent.domain.forecast_performance_missing_data_policy import (
    ForecastPerformanceMissingDataPolicy,
)
from forex_agent.domain.forecast_performance_sample_adequacy import (
    ForecastPerformanceSampleAdequacy,
)
from forex_agent.domain.forecast_performance_snapshot import (
    ForecastPerformanceSnapshot,
    ForecastPerformanceSnapshotMember,
)
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.forecast_target_period import ForecastTargetPeriod
from forex_agent.domain.forecast_target_period_kind import ForecastTargetPeriodKind
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.intelligence_source_kind import IntelligenceSourceKind
from forex_agent.domain.source_evidence_kind import SourceEvidenceKind
from forex_agent.domain.source_provenance_evidence import SourceProvenanceEvidence
from forex_agent.domain.structured_forecast_evaluation_vintage import (
    StructuredForecastEvaluationVintage,
)
from forex_agent.domain.structured_forecast_vintage import StructuredForecastVintage
from forex_agent.domain.timestamps import UtcTimestamp
from tests.fakes.forecast_evaluation_repository import FakeForecastEvaluationRepository
from tests.fakes.forecast_outcome_repository import FakeForecastOutcomeRepository
from tests.fakes.forecast_performance_repository import FakeForecastPerformanceRepository
from tests.fakes.source_registry_repository import FakeSourceRegistryRepository
from tests.fakes.structured_forecast_repository import FakeStructuredForecastRepository

_PUBLISHER = "__fx67_test_publisher__"
_FORECASTER = "__fx67_test_forecaster__"


def _ts(hour: int, day: int = 1) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, day, hour, tzinfo=UTC))


def _review(reviewed_at: UtcTimestamp) -> EvidenceAuthenticationReview:
    return EvidenceAuthenticationReview(
        reviewed_by="tester", review_method="synthetic", reviewed_at=reviewed_at
    )


def _evidence(doc_id: str) -> ForecastEvidenceReference:
    return ForecastEvidenceReference(
        evidence_kind=ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
        description="synthetic test evidence",
        document_identifier=doc_id,
    )


def _attribution(**overrides: object) -> ForecastAttribution:
    defaults: dict[str, object] = {
        "kind": ForecastAttributionKind.AGGREGATE_SURVEY_CONSENSUS,
        "publisher_source_key": _PUBLISHER,
    }
    defaults.update(overrides)
    return ForecastAttribution(**defaults)  # type: ignore[arg-type]


def _population_member(
    evaluation_key: str,
    outcome_key: str,
    *,
    meeting_id: str = "M1",
    forecast_value: Decimal = Decimal("3.75"),
    observed_value: Decimal = Decimal("3.25"),
    evaluation_availability: UtcTimestamp | None = None,
    attribution: ForecastAttribution | None = None,
    evaluation_mode: ForecastProvenanceMode = ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
) -> ForecastPerformancePopulationMember:
    evaluation_availability = evaluation_availability or _ts(10)
    period = ForecastTargetPeriod(
        period_kind=ForecastTargetPeriodKind.POLICY_MEETING, policy_meeting_identifier=meeting_id
    )
    forecast_vintage = StructuredForecastVintage(
        claim_key=f"{evaluation_key}-claim",
        revision_sequence=0,
        availability=evaluation_availability,
        algorithm_version="test_v1",
        forecast_type=ForecastType.NUMERIC_POINT,
        target_key="CA_POLICY_RATE_LEVEL_AFTER_MEETING",
        target_period=period,
        attribution=attribution or _attribution(),
        provenance_mode=evaluation_mode,
        evidence=_evidence(f"{evaluation_key}-doc"),
        numeric_value=forecast_value,
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
        evidence=_evidence(f"{outcome_key}-doc"),
        authentication_review=_review(evaluation_availability),
        provenance_mode=evaluation_mode,
        numeric_value=observed_value,
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
        evaluation_mode=evaluation_mode,
        algorithm_version="fx65_v1",
        availability=evaluation_availability,
        result=ForecastEvaluationResult(
            metric=ForecastEvaluationMetric.NUMERIC_ERROR,
            signed_error=observed_value - forecast_value,
            absolute_error=abs(observed_value - forecast_value),
            unit="PERCENT",
        ),
        forecast_authentication_review=_review(evaluation_availability),
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
        "rationale": "fx67 test cohort",
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
        "rationale": "fx67 test methodology",
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
        "rationale": "fx67 test benchmark",
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
) -> ForecastPerformancePopulation:
    cohort = cohort or _cohort()
    members = members if members is not None else (_population_member("eval-a", "outcome-a"),)
    return ForecastPerformancePopulation(
        cohort=cohort,
        knowledge_cutoff=knowledge_cutoff or _ts(13),
        raw_candidate_count=len(members) + len(exclusions),
        accepted=members,
        exclusions=exclusions,
    )


class _Repos:
    """Wires every fake repository an inspection use case needs,
    PLUS seeds the raw evaluation/forecast/outcome vintage tables so
    `GetForecastPerformanceMembers`/`GetForecastEvaluationInspection`
    can resolve each member independently of the snapshot's own
    embedded `(key, revision)` refs -- exactly mirroring how the real
    repositories are genuinely separate tables."""

    def __init__(self) -> None:
        self.performance = FakeForecastPerformanceRepository()
        self.evaluation = FakeForecastEvaluationRepository()
        self.forecast = FakeStructuredForecastRepository()
        self.outcome = FakeForecastOutcomeRepository()
        self.registry = FakeSourceRegistryRepository()

    async def register_identity(
        self, source_key: str, display_name: str, *, availability: UtcTimestamp | None = None
    ) -> None:
        availability = availability or _ts(1)
        await RecordSourceIdentityVintage(self.registry)(
            source_key=source_key,
            source_kind=IntelligenceSourceKind.ORGANIZATION,
            registered_at=availability,
            availability=availability,
            algorithm_version="fx62_v1",
            display_name=display_name,
            aliases=(),
            authoritative_identifier=None,
            canonical_website=None,
            evidence=SourceProvenanceEvidence(
                evidence_kind=SourceEvidenceKind.ADAPTER_CONFIGURATION, description="test"
            ),
        )

    def seed_member(self, member: ForecastPerformancePopulationMember) -> None:
        self.forecast.vintages[member.forecast_vintage.claim_key] = [member.forecast_vintage]
        self.outcome.vintages[member.outcome_vintage.outcome_key] = [member.outcome_vintage]
        self.evaluation.vintages[member.evaluation.evaluation_key] = [member.evaluation]

    def seed_population(self, population: ForecastPerformancePopulation) -> None:
        for member in population.accepted:
            self.seed_member(member)

    def consistent_snapshot(
        self,
        population: ForecastPerformancePopulation,
        *,
        snapshot_key: str = "test-snapshot",
        methodology_key: str = "test-methodology",
        availability: UtcTimestamp | None = None,
        benchmark: ForecastPerformanceBenchmarkDefinition | None = None,
        benchmark_population: ForecastPerformancePopulation | None = None,
        **overrides: object,
    ) -> ForecastPerformanceSnapshot:
        availability = availability or _ts(14)
        numeric, categorical, comparison = CalculateForecastPerformance()(
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
            "methodology_version_sequence": 0,
            "cohort_key": population.cohort.cohort_key,
            "cohort_version_sequence": population.cohort.version_sequence,
            "evaluation_mode": population.cohort.evaluation_mode,
            "members": members,
            "exclusions": population.exclusions,
            "benchmark_comparison": comparison,
            "diagnostics": diagnostics,
            "knowledge_cutoff": population.knowledge_cutoff,
            "availability": availability,
            "algorithm_version": "fx66_v1",
            "numeric_summary": numeric,
            "categorical_summary": categorical,
        }
        defaults.update(overrides)
        return ForecastPerformanceSnapshot(**defaults)  # type: ignore[arg-type]

    async def record(
        self,
        snapshot: ForecastPerformanceSnapshot,
        cohort: ForecastPerformanceCohortDefinition,
        methodology: ForecastPerformanceMethodology,
        benchmark: ForecastPerformanceBenchmarkDefinition | None = None,
    ) -> None:
        await self.performance.add_cohort_version(cohort)
        await self.performance.add_methodology_version(methodology)
        if benchmark is not None:
            await self.performance.add_benchmark_version(benchmark)
        await self.performance.add_snapshot_vintage(snapshot)

    def get_inspection(self) -> GetForecastPerformanceInspection:
        return GetForecastPerformanceInspection(self.performance, self.evaluation, self.registry)

    def get_members(self) -> GetForecastPerformanceMembers:
        return GetForecastPerformanceMembers(
            self.performance, self.evaluation, self.forecast, self.outcome, self.registry
        )

    def get_exclusions(self) -> GetForecastPerformanceExclusions:
        return GetForecastPerformanceExclusions(self.performance)

    def get_benchmark_inspection(self) -> GetForecastPerformanceBenchmarkInspection:
        return GetForecastPerformanceBenchmarkInspection(self.performance)

    def get_evaluation_inspection(self) -> GetForecastEvaluationInspection:
        return GetForecastEvaluationInspection(
            self.evaluation, self.forecast, self.outcome, self.registry
        )


_MODE = ForecastPerformanceInspectionMode.RETROSPECTIVE_RESEARCH


async def _seed_and_record(
    repos: _Repos,
    *,
    cohort: ForecastPerformanceCohortDefinition | None = None,
    members: tuple[ForecastPerformancePopulationMember, ...] | None = None,
    exclusions: tuple[tuple[str, ForecastPerformanceExclusionReason], ...] = (),
    benchmark: ForecastPerformanceBenchmarkDefinition | None = None,
    benchmark_population: ForecastPerformancePopulation | None = None,
) -> tuple[ForecastPerformancePopulation, ForecastPerformanceSnapshot]:
    population = _population(cohort=cohort, members=members, exclusions=exclusions)
    repos.seed_population(population)
    snapshot = repos.consistent_snapshot(
        population, benchmark=benchmark, benchmark_population=benchmark_population
    )
    await repos.record(
        snapshot,
        population.cohort,
        _methodology(cohort_key=population.cohort.cohort_key),
        benchmark,
    )
    return population, snapshot


# --- A: Snapshot summary ---------------------------------------------------


async def test_a_summary_reports_correct_cohort_methodology_and_cutoff() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    await _seed_and_record(repos)

    inspection = await repos.get_inspection()("test-snapshot", _MODE, _ts(20))

    assert inspection.cohort is not None and inspection.cohort.cohort_key == "test-cohort"
    assert inspection.methodology is not None and inspection.methodology.methodology_key == (
        "test-methodology"
    )
    assert inspection.snapshot.evaluation_mode is ForecastProvenanceMode.RETROSPECTIVE_RESEARCH
    assert inspection.snapshot.knowledge_cutoff == _ts(13)
    assert inspection.snapshot.availability == _ts(14)


async def test_a_summary_reports_exact_stored_numeric_metrics() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    await _seed_and_record(repos)

    inspection = await repos.get_inspection()("test-snapshot", _MODE, _ts(20))

    assert inspection.snapshot.numeric_summary is not None
    assert inspection.snapshot.numeric_summary.mean_absolute_error == Decimal("0.50")


async def test_a_missing_benchmark_is_represented_explicitly_not_as_zero() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    await _seed_and_record(repos)

    inspection = await repos.get_inspection()("test-snapshot", _MODE, _ts(20))

    assert (
        inspection.snapshot.benchmark_comparison.status
        is ForecastPerformanceBenchmarkComparisonStatus.BENCHMARK_UNAVAILABLE
    )
    assert inspection.snapshot.benchmark_comparison.source_mean_absolute_error is None


async def test_a_no_inferred_reputation_rating_exists_anywhere_in_result() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    _, snapshot = await _seed_and_record(repos)

    assert not hasattr(snapshot, "reputation")
    assert not hasattr(snapshot, "rating")
    assert not hasattr(snapshot, "rank")


# --- B: Membership and evidence ---------------------------------------------


async def test_b_member_shows_exact_pinned_forecast_and_outcome_vintage() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    await _seed_and_record(repos)

    page = await repos.get_members()("test-snapshot", _MODE, _ts(20), limit=10)

    assert len(page.members) == 1
    member = page.members[0]
    assert isinstance(member, ForecastEvaluationInspection)
    assert isinstance(member.forecast_vintage, StructuredForecastVintage)
    assert member.forecast_vintage.numeric_value == Decimal("3.75")
    assert isinstance(member.outcome_vintage, ForecastOutcomeVintage)
    assert member.outcome_vintage.numeric_value == Decimal("3.25")
    assert member.evaluation.result.signed_error == Decimal("-0.50")


async def test_b_attribution_resolves_publisher_display_name() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Bank of Somewhere")
    await _seed_and_record(repos)

    page = await repos.get_members()("test-snapshot", _MODE, _ts(20), limit=10)
    member = page.members[0]
    assert isinstance(member, ForecastEvaluationInspection)
    assert member.originator is not None
    assert member.originator.publisher_display_name == "Bank of Somewhere"
    assert member.originator.attribution.kind is ForecastAttributionKind.AGGREGATE_SURVEY_CONSENSUS


async def test_b_aggregate_consensus_is_never_attributed_as_publishers_own_forecast() -> None:
    """A Bank-of-Canada-style survey median must appear as an
    aggregate consensus published BY the institution, never as the
    institution's OWN forecast (Section 8)."""
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Bank of Canada")
    await _seed_and_record(repos)

    page = await repos.get_members()("test-snapshot", _MODE, _ts(20), limit=10)
    member = page.members[0]
    assert isinstance(member, ForecastEvaluationInspection)
    assert member.originator is not None
    assert member.originator.attribution.kind is ForecastAttributionKind.AGGREGATE_SURVEY_CONSENSUS
    assert member.originator.attribution.forecaster_source_key is None


async def test_b_anonymous_respondent_is_never_given_an_invented_name() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Survey House")
    anonymous = _attribution(kind=ForecastAttributionKind.ANONYMOUS_RESPONDENT)
    member = _population_member("eval-a", "outcome-a", attribution=anonymous)
    await _seed_and_record(repos, members=(member,))

    page = await repos.get_members()("test-snapshot", _MODE, _ts(20), limit=10)
    resolved = page.members[0]
    assert isinstance(resolved, ForecastEvaluationInspection)
    assert resolved.originator is not None
    assert resolved.originator.forecaster_display_name is None
    assert resolved.originator.attribution.forecaster_source_key is None


async def test_b_named_institution_resolves_forecaster_display_name() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Survey House")
    await repos.register_identity(_FORECASTER, "Dr. Jane Economist")
    named = _attribution(
        kind=ForecastAttributionKind.NAMED_INSTITUTION, forecaster_source_key=_FORECASTER
    )
    member = _population_member("eval-a", "outcome-a", attribution=named)
    await _seed_and_record(repos, members=(member,))

    page = await repos.get_members()("test-snapshot", _MODE, _ts(20), limit=10)
    resolved = page.members[0]
    assert isinstance(resolved, ForecastEvaluationInspection)
    assert resolved.originator is not None
    assert resolved.originator.forecaster_display_name == "Dr. Jane Economist"


async def test_b_later_evaluation_revision_does_not_alter_frozen_member_inspection() -> None:
    """Appending a LATER revision of the same evaluation_key must not
    change what an ALREADY-recorded snapshot's own member inspection
    shows -- the snapshot pinned revision 0 forever."""
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    await _seed_and_record(repos)

    corrected = StructuredForecastEvaluationVintage(
        evaluation_key="eval-a",
        revision_sequence=1,
        forecast_claim_key="eval-a-claim",
        forecast_revision_sequence=0,
        protocol_key="test-protocol",
        protocol_version_sequence=0,
        outcome_definition_key="test-def",
        outcome_definition_version_sequence=0,
        outcome_key="outcome-a",
        outcome_revision_sequence=0,
        evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        algorithm_version="fx65_v1",
        availability=_ts(20),
        result=ForecastEvaluationResult(
            metric=ForecastEvaluationMetric.NUMERIC_ERROR,
            signed_error=Decimal("-9.99"),
            absolute_error=Decimal("9.99"),
            unit="PERCENT",
        ),
        forecast_authentication_review=_review(_ts(20)),
    )
    repos.evaluation.vintages["eval-a"].append(corrected)

    page = await repos.get_members()("test-snapshot", _MODE, _ts(20), limit=10)
    member = page.members[0]
    assert isinstance(member, ForecastEvaluationInspection)
    assert member.evaluation.revision_sequence == 0
    assert member.evaluation.result.signed_error == Decimal("-0.50")


async def test_b_missing_linked_evidence_is_surfaced_explicitly() -> None:
    """If `list_vintages_for_claim`/`list_vintages_for_outcome` cannot
    resolve what the snapshot's own member pins, an `Unresolved
    EvidenceReference` is returned -- never invented/current data."""
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    population, _ = await _seed_and_record(repos)
    del repos.forecast.vintages[population.accepted[0].forecast_vintage.claim_key]

    page = await repos.get_members()("test-snapshot", _MODE, _ts(20), limit=10)
    member = page.members[0]
    assert isinstance(member, ForecastEvaluationInspection)
    assert isinstance(member.forecast_vintage, UnresolvedEvidenceReference)
    assert isinstance(member.outcome_vintage, UnresolvedEvidenceReference)
    assert member.originator is None


async def test_b_categorical_member_shows_categorical_values() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    cohort = _cohort(
        target_key="CA_POLICY_RATE_DECISION_HIKE_HOLD_CUT",
        forecast_type=ForecastType.CATEGORICAL_EVENT,
    )
    period = ForecastTargetPeriod(
        period_kind=ForecastTargetPeriodKind.POLICY_MEETING, policy_meeting_identifier="M1"
    )
    forecast_vintage = StructuredForecastVintage(
        claim_key="eval-cat-claim",
        revision_sequence=0,
        availability=_ts(10),
        algorithm_version="test_v1",
        forecast_type=ForecastType.CATEGORICAL_EVENT,
        target_key="CA_POLICY_RATE_DECISION_HIKE_HOLD_CUT",
        target_period=period,
        attribution=_attribution(),
        provenance_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        evidence=_evidence("eval-cat-doc"),
        categorical_outcome="HOLD",
    )
    outcome_vintage = ForecastOutcomeVintage(
        outcome_key="outcome-cat",
        revision_sequence=0,
        definition_key="test-def-cat",
        definition_version_sequence=0,
        availability=_ts(10),
        target_period=period,
        outcome_type=ForecastType.CATEGORICAL_EVENT,
        evidence=_evidence("outcome-cat-doc"),
        authentication_review=_review(_ts(10)),
        provenance_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        categorical_outcome="HOLD",
    )
    evaluation = StructuredForecastEvaluationVintage(
        evaluation_key="eval-cat",
        revision_sequence=0,
        forecast_claim_key="eval-cat-claim",
        forecast_revision_sequence=0,
        protocol_key="test-protocol",
        protocol_version_sequence=0,
        outcome_definition_key="test-def-cat",
        outcome_definition_version_sequence=0,
        outcome_key="outcome-cat",
        outcome_revision_sequence=0,
        evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        algorithm_version="fx65_v1",
        availability=_ts(10),
        result=ForecastEvaluationResult(
            metric=ForecastEvaluationMetric.CATEGORICAL_MATCH,
            categorical_result=CategoricalEvaluationResult.MATCH,
        ),
        forecast_authentication_review=_review(_ts(10)),
    )
    member = ForecastPerformancePopulationMember(evaluation, forecast_vintage, outcome_vintage)
    await _seed_and_record(repos, cohort=cohort, members=(member,))

    page = await repos.get_members()("test-snapshot", _MODE, _ts(20), limit=10)
    resolved = page.members[0]
    assert isinstance(resolved, ForecastEvaluationInspection)
    assert isinstance(resolved.forecast_vintage, StructuredForecastVintage)
    assert resolved.forecast_vintage.categorical_outcome == "HOLD"


# --- C: Exclusions and limitations ------------------------------------------


async def test_c_accepted_and_excluded_counts_reconcile() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    members = (
        _population_member("eval-a", "outcome-a"),
        _population_member("eval-b", "outcome-b", meeting_id="M2"),
    )
    exclusions = (("eval-z", ForecastPerformanceExclusionReason.KNOWN_DUPLICATE_SYNDICATED),)
    await _seed_and_record(repos, members=members, exclusions=exclusions)

    inspection = await repos.get_inspection()("test-snapshot", _MODE, _ts(20))
    excl_page = await repos.get_exclusions()("test-snapshot", _MODE, _ts(20), limit=10)

    assert inspection.snapshot.diagnostics.accepted_count == 2
    assert len(excl_page.exclusions) == 1
    assert (
        inspection.snapshot.diagnostics.accepted_count
        + sum(c for _, c in inspection.snapshot.diagnostics.excluded_by_reason)
        == inspection.snapshot.diagnostics.raw_candidate_count
    )


async def test_c_exclusion_reason_is_preserved_exactly() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    exclusions = (("eval-z", ForecastPerformanceExclusionReason.INCOMPATIBLE_TARGET),)
    await _seed_and_record(repos, exclusions=exclusions)

    excl_page = await repos.get_exclusions()("test-snapshot", _MODE, _ts(20), limit=10)

    assert excl_page.exclusions == (
        ("eval-z", ForecastPerformanceExclusionReason.INCOMPATIBLE_TARGET),
    )


async def test_c_empty_snapshot_has_no_fabricated_exclusions() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    await _seed_and_record(repos, members=())

    excl_page = await repos.get_exclusions()("test-snapshot", _MODE, _ts(20), limit=10)
    inspection = await repos.get_inspection()("test-snapshot", _MODE, _ts(20))

    assert excl_page.exclusions == ()
    assert inspection.snapshot.diagnostics.accepted_count == 0
    assert inspection.snapshot.diagnostics.sample_adequacy is (
        ForecastPerformanceSampleAdequacy.INSUFFICIENT_DATA
    )


async def test_c_insufficient_data_is_appropriately_explained() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    await _seed_and_record(repos)

    inspection = await repos.get_inspection()("test-snapshot", _MODE, _ts(20))

    assert (
        inspection.limitations.sample_adequacy
        is ForecastPerformanceSampleAdequacy.INSUFFICIENT_DATA
    )
    assert "too few" in inspection.limitations.sample_adequacy_explanation.lower()


async def test_c_comparable_sample_is_never_represented_as_demonstrated_skill() -> None:
    limitations = GetForecastPerformanceLimitations()
    from forex_agent.domain.forecast_performance_benchmark_comparison import (
        ForecastPerformanceBenchmarkComparison,
    )
    from forex_agent.domain.forecast_performance_sample_diagnostics import (
        ForecastPerformanceSampleDiagnostics,
    )

    diagnostics = ForecastPerformanceSampleDiagnostics(
        raw_candidate_count=30,
        accepted_count=30,
        excluded_by_reason=(),
        unique_forecast_issue_count=30,
        unique_target_event_count=30,
        distinct_target_period_count=30,
        benchmark_paired_count=0,
        production_count=30,
        research_count=0,
        missing_outcome_rate=Decimal("0"),
        earliest_availability=_ts(1),
        latest_availability=_ts(10),
        sample_adequacy=ForecastPerformanceSampleAdequacy.COMPARABLE_SAMPLE,
    )
    result = limitations(
        diagnostics,
        None,
        ForecastPerformanceBenchmarkComparison(
            status=ForecastPerformanceBenchmarkComparisonStatus.BENCHMARK_UNAVAILABLE
        ),
        ForecastProvenanceMode.PRODUCTION_OBSERVED,
    )
    assert "NOT" in result.sample_adequacy_explanation
    assert "skill" in result.sample_adequacy_explanation.lower()


async def test_c_inference_supported_is_never_invented() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    _, snapshot = await _seed_and_record(repos)
    assert (
        snapshot.diagnostics.sample_adequacy
        is not ForecastPerformanceSampleAdequacy.INFERENCE_SUPPORTED
    )


async def test_c_horizon_limitation_is_always_visible() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    await _seed_and_record(repos)

    inspection = await repos.get_inspection()("test-snapshot", _MODE, _ts(20))

    assert HORIZON_LIMITATION in inspection.limitations.limitations


async def test_c_unreachable_exclusion_reasons_are_not_fabricated() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    await _seed_and_record(repos)

    excl_page = await repos.get_exclusions()("test-snapshot", _MODE, _ts(20), limit=10)

    reasons = {reason for _, reason in excl_page.exclusions}
    assert ForecastPerformanceExclusionReason.NOT_YET_AVAILABLE not in reasons
    assert ForecastPerformanceExclusionReason.MISSING_OR_UNRESOLVED_OUTCOME not in reasons


# --- D: Benchmarks -----------------------------------------------------------


async def test_d_correct_benchmark_definition_and_paired_count() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    benchmark = _benchmark()
    await _seed_and_record(repos, benchmark=benchmark)

    inspection = await repos.get_benchmark_inspection()("test-snapshot", _MODE, _ts(20))

    assert inspection.benchmark is not None
    assert inspection.benchmark.benchmark_key == "test-benchmark"
    assert inspection.comparison.paired_count == 1
    assert inspection.benchmark_unresolved is False


async def test_d_missing_benchmark_is_reported_prominently() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    await _seed_and_record(repos)

    inspection = await repos.get_benchmark_inspection()("test-snapshot", _MODE, _ts(20))

    assert (
        inspection.comparison.status
        is ForecastPerformanceBenchmarkComparisonStatus.BENCHMARK_UNAVAILABLE
    )
    assert inspection.benchmark is None
    assert inspection.is_complete_pairing is False


async def test_d_no_fabricated_relative_performance_metric_without_benchmark() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    await _seed_and_record(repos)

    inspection = await repos.get_benchmark_inspection()("test-snapshot", _MODE, _ts(20))

    assert inspection.comparison.mean_absolute_error_difference is None
    assert inspection.comparison.relative_mae_improvement is None


# --- E: Historical PIT -------------------------------------------------------


async def test_e_snapshot_invisible_before_recording() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    await _seed_and_record(repos)

    with pytest.raises(SnapshotNotVisibleForInspectionError):
        await repos.get_inspection()("test-snapshot", _MODE, _ts(5))


async def test_e_snapshot_available_exactly_at_recording_timestamp() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    await _seed_and_record(repos)

    inspection = await repos.get_inspection()("test-snapshot", _MODE, _ts(14))
    assert inspection.snapshot.snapshot_key == "test-snapshot"


async def test_e_retrospective_research_excluded_from_production_query() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    await _seed_and_record(repos)

    with pytest.raises(SnapshotNotVisibleForInspectionError):
        await repos.get_inspection()(
            "test-snapshot", ForecastPerformanceInspectionMode.PRODUCTION, _ts(20)
        )


async def test_e_repeated_historical_queries_reproduce_identical_content() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    await _seed_and_record(repos)

    first = await repos.get_inspection()("test-snapshot", _MODE, _ts(20))
    second = await repos.get_inspection()("test-snapshot", _MODE, _ts(20))

    assert first.snapshot == second.snapshot
    assert first.limitations == second.limitations


# --- F: Pagination and performance -------------------------------------------


async def test_f_stable_ordering_by_evaluation_key() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    members = tuple(
        _population_member(f"eval-{i}", f"outcome-{i}", meeting_id=f"M{i}") for i in range(5)
    )
    await _seed_and_record(repos, members=members)

    page = await repos.get_members()("test-snapshot", _MODE, _ts(20), limit=10)

    keys = [
        m.evaluation.evaluation_key
        for m in page.members
        if isinstance(m, ForecastEvaluationInspection)
    ]
    assert keys == sorted(keys)


async def test_f_first_and_last_page() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    members = tuple(
        _population_member(f"eval-{i}", f"outcome-{i}", meeting_id=f"M{i}") for i in range(5)
    )
    await _seed_and_record(repos, members=members)

    first = await repos.get_members()("test-snapshot", _MODE, _ts(20), limit=2)
    assert len(first.members) == 2
    assert first.next_cursor is not None

    second = await repos.get_members()(
        "test-snapshot", _MODE, _ts(20), limit=2, after_key=first.next_cursor
    )
    assert len(second.members) == 2
    assert second.next_cursor is not None

    last = await repos.get_members()(
        "test-snapshot", _MODE, _ts(20), limit=2, after_key=second.next_cursor
    )
    assert len(last.members) == 1
    assert last.next_cursor is None


async def test_f_empty_results_for_snapshot_with_no_members() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    await _seed_and_record(repos, members=())

    page = await repos.get_members()("test-snapshot", _MODE, _ts(20), limit=10)
    assert page.members == ()
    assert page.next_cursor is None


async def test_f_invalid_page_bounds_rejected() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    await _seed_and_record(repos)

    with pytest.raises(InvalidInspectionPageBoundsError):
        await repos.get_members()("test-snapshot", _MODE, _ts(20), limit=0)
    with pytest.raises(InvalidInspectionPageBoundsError):
        await repos.get_members()("test-snapshot", _MODE, _ts(20), limit=-1)


async def test_f_list_snapshots_pagination_boundaries() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")

    for i in range(3):
        cohort = _cohort(cohort_key=f"cohort-{i}")
        members = (_population_member(f"eval-{i}", f"outcome-{i}", meeting_id=f"M{i}"),)
        population = _population(cohort=cohort, members=members)
        repos.seed_population(population)
        snapshot = repos.consistent_snapshot(
            population, snapshot_key=f"snapshot-{i}", methodology_key=f"methodology-{i}"
        )
        await repos.record(
            snapshot,
            cohort,
            _methodology(methodology_key=f"methodology-{i}", cohort_key=cohort.cohort_key),
        )

    list_snapshots = ListForecastPerformanceSnapshots(repos.performance)
    first_page = await list_snapshots(_MODE, _ts(20), limit=2)
    assert len(first_page.snapshot_keys) == 2
    assert first_page.next_cursor is not None

    second_page = await list_snapshots(_MODE, _ts(20), limit=2, after_key=first_page.next_cursor)
    assert len(second_page.snapshot_keys) == 1
    assert second_page.next_cursor is None


# --- FX-67H (F67-01): PIT-safe snapshot discovery ---------------------------

_PRODUCTION_MODE = ForecastPerformanceInspectionMode.PRODUCTION


async def _record_snapshot(
    repos: _Repos,
    *,
    cohort_key: str,
    snapshot_key: str,
    availability: UtcTimestamp,
    evaluation_mode: ForecastProvenanceMode = ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
) -> None:
    cohort = _cohort(cohort_key=cohort_key, evaluation_mode=evaluation_mode)
    members = (_population_member(f"eval-{snapshot_key}", f"outcome-{snapshot_key}"),)
    population = _population(cohort=cohort, members=members)
    repos.seed_population(population)
    snapshot = repos.consistent_snapshot(
        population,
        snapshot_key=snapshot_key,
        methodology_key=f"{snapshot_key}-methodology",
        availability=availability,
    )
    await repos.record(
        snapshot,
        cohort,
        _methodology(methodology_key=f"{snapshot_key}-methodology", cohort_key=cohort_key),
    )


async def test_h1_production_snapshot_available_before_cutoff_is_included() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    await _record_snapshot(
        repos,
        cohort_key="prod-cohort",
        snapshot_key="prod-snapshot",
        availability=_ts(10),
        evaluation_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED,
    )

    list_snapshots = ListForecastPerformanceSnapshots(repos.performance)
    page = await list_snapshots(_PRODUCTION_MODE, _ts(20), limit=10)
    assert "prod-snapshot" in page.snapshot_keys


async def test_h1_production_snapshot_first_recorded_after_cutoff_is_excluded() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    await _record_snapshot(
        repos,
        cohort_key="prod-cohort",
        snapshot_key="prod-snapshot",
        availability=_ts(14),
        evaluation_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED,
    )

    list_snapshots = ListForecastPerformanceSnapshots(repos.performance)
    page = await list_snapshots(_PRODUCTION_MODE, _ts(10), limit=10)
    assert "prod-snapshot" not in page.snapshot_keys


async def test_h1_research_only_snapshot_excluded_from_production_listing() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    await _record_snapshot(
        repos, cohort_key="research-cohort", snapshot_key="research-snapshot", availability=_ts(10)
    )

    list_snapshots = ListForecastPerformanceSnapshots(repos.performance)
    page = await list_snapshots(_PRODUCTION_MODE, _ts(20), limit=10)
    assert "research-snapshot" not in page.snapshot_keys


async def test_h1_research_snapshot_included_in_research_listing_when_available() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    await _record_snapshot(
        repos, cohort_key="research-cohort", snapshot_key="research-snapshot", availability=_ts(10)
    )

    list_snapshots = ListForecastPerformanceSnapshots(repos.performance)
    page = await list_snapshots(_MODE, _ts(20), limit=10)
    assert "research-snapshot" in page.snapshot_keys


async def test_h1_snapshot_invisible_before_first_recording() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    await _record_snapshot(repos, cohort_key="c", snapshot_key="s", availability=_ts(14))

    list_snapshots = ListForecastPerformanceSnapshots(repos.performance)
    page = await list_snapshots(_MODE, _ts(10), limit=10)
    assert "s" not in page.snapshot_keys


async def test_h1_snapshot_visible_exactly_at_recording_availability() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    await _record_snapshot(repos, cohort_key="c", snapshot_key="s", availability=_ts(14))

    list_snapshots = ListForecastPerformanceSnapshots(repos.performance)
    page = await list_snapshots(_MODE, _ts(14), limit=10)
    assert "s" in page.snapshot_keys


async def test_h1_earlier_visible_vintage_remains_discoverable_after_future_revision() -> None:
    """The CORE F67-01 fix: a snapshot's revision 0 is visible by
    `_ts(14)`; appending a revision 1 available only on day 2 must NOT
    make the key disappear from a historical query at `_ts(20)` --
    visibility is determined by existence of at least one qualifying
    vintage, never merely the overall-latest one."""
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    cohort = _cohort(cohort_key="c")
    members = (_population_member("eval-s", "outcome-s"),)
    population = _population(cohort=cohort, members=members)
    repos.seed_population(population)
    revision_0 = repos.consistent_snapshot(
        population, snapshot_key="s", methodology_key="s-methodology", availability=_ts(14)
    )
    await repos.record(
        revision_0, cohort, _methodology(methodology_key="s-methodology", cohort_key="c")
    )

    revision_1 = repos.consistent_snapshot(
        population,
        snapshot_key="s",
        methodology_key="s-methodology",
        availability=_ts(6, day=2),
        revision_sequence=1,
    )
    await repos.performance.add_snapshot_vintage(revision_1)

    list_snapshots = ListForecastPerformanceSnapshots(repos.performance)
    page = await list_snapshots(_MODE, _ts(20), limit=10)
    assert "s" in page.snapshot_keys


async def test_h1_new_future_snapshot_does_not_alter_historical_discovery_results() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    await _record_snapshot(repos, cohort_key="c1", snapshot_key="s1", availability=_ts(14))

    list_snapshots = ListForecastPerformanceSnapshots(repos.performance)
    before = await list_snapshots(_MODE, _ts(20), limit=10)

    await _record_snapshot(
        repos, cohort_key="c2", snapshot_key="s2-future", availability=_ts(6, day=2)
    )

    after = await list_snapshots(_MODE, _ts(20), limit=10)
    assert before.snapshot_keys == after.snapshot_keys


async def test_h1_multiple_snapshot_keys_with_mixed_modes_and_dates() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    await _record_snapshot(
        repos,
        cohort_key="prod-cohort",
        snapshot_key="prod-snapshot",
        availability=_ts(10),
        evaluation_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED,
    )
    await _record_snapshot(
        repos, cohort_key="research-cohort", snapshot_key="research-snapshot", availability=_ts(16)
    )

    list_snapshots = ListForecastPerformanceSnapshots(repos.performance)

    prod_page = await list_snapshots(_PRODUCTION_MODE, _ts(20), limit=10)
    assert "prod-snapshot" in prod_page.snapshot_keys
    assert "research-snapshot" not in prod_page.snapshot_keys

    research_page = await list_snapshots(_MODE, _ts(20), limit=10)
    assert "prod-snapshot" in research_page.snapshot_keys
    assert "research-snapshot" in research_page.snapshot_keys

    early_research_page = await list_snapshots(_MODE, _ts(12), limit=10)
    assert "prod-snapshot" in early_research_page.snapshot_keys
    assert "research-snapshot" not in early_research_page.snapshot_keys


async def test_h1_disallowed_records_do_not_consume_page_capacity() -> None:
    """If filtering happened AFTER `LIMIT` rather than before, the
    disallowed 'a-snapshot' (lexicographically first, but only
    available in the future) would wrongly consume one slot of a
    2-row page, leaving only 1 real result instead of 2."""
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    await _record_snapshot(
        repos, cohort_key="cohort-a", snapshot_key="a-snapshot", availability=_ts(6, day=2)
    )
    await _record_snapshot(
        repos, cohort_key="cohort-b", snapshot_key="b-snapshot", availability=_ts(14)
    )
    await _record_snapshot(
        repos, cohort_key="cohort-c", snapshot_key="c-snapshot", availability=_ts(14)
    )

    list_snapshots = ListForecastPerformanceSnapshots(repos.performance)
    page = await list_snapshots(_MODE, _ts(20), limit=2)

    assert page.snapshot_keys == ("b-snapshot", "c-snapshot")


async def test_h1_cohort_filter_combines_with_mode_and_pit_filters() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    await _record_snapshot(
        repos,
        cohort_key="cohort-x",
        snapshot_key="x-snapshot",
        availability=_ts(14),
        evaluation_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED,
    )
    await _record_snapshot(
        repos,
        cohort_key="cohort-y",
        snapshot_key="y-snapshot",
        availability=_ts(14),
        evaluation_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED,
    )

    list_snapshots = ListForecastPerformanceSnapshots(repos.performance)
    page = await list_snapshots(_PRODUCTION_MODE, _ts(20), cohort_key="cohort-x", limit=10)

    assert page.snapshot_keys == ("x-snapshot",)


async def test_h1_empty_page_when_nothing_qualifies() -> None:
    repos = _Repos()
    await repos.register_identity(_PUBLISHER, "Test Publisher Org")
    await _record_snapshot(repos, cohort_key="c", snapshot_key="s", availability=_ts(14))

    list_snapshots = ListForecastPerformanceSnapshots(repos.performance)
    page = await list_snapshots(_PRODUCTION_MODE, _ts(20), limit=10)

    assert page.snapshot_keys == ()
    assert page.next_cursor is None


async def test_h1_invalid_limit_rejected() -> None:
    repos = _Repos()
    list_snapshots = ListForecastPerformanceSnapshots(repos.performance)
    with pytest.raises(InvalidInspectionPageBoundsError):
        await list_snapshots(_MODE, _ts(20), limit=0)
    with pytest.raises(InvalidInspectionPageBoundsError):
        await list_snapshots(_MODE, _ts(20), limit=-1)


def test_h1_list_snapshots_requires_explicit_mode_and_as_of() -> None:
    """Section 2's own "no implicit mode or implicit current-time
    fallback" rule, enforced structurally: `mode`/`as_of` are
    positional-or-keyword with NO default anywhere in the signature."""
    import inspect

    params = inspect.signature(ListForecastPerformanceSnapshots.__call__).parameters
    assert params["mode"].default is inspect.Parameter.empty
    assert params["as_of"].default is inspect.Parameter.empty
