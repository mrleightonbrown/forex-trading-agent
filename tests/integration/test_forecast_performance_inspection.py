"""FX-67 Section 20.G: real-Postgres integration tests for the
forecast-performance inspection use cases -- real stored snapshot
inspection, exact evidence FK traversal, PIT mode filtering,
historical reconstruction after later evidence is appended,
transaction isolation, and "no evidence-table mutations."

Builds its own small, real evaluation chain through the SAME
production use cases FX-64/65/66 already use (`RecordStructuredForecast`
/`RecordForecastOutcome`/`EvaluateStructuredForecast`/`BuildForecastPerformance
PopulationAsOf`/`RecordForecastPerformanceSnapshot`), rather than hand-
inserting rows, so this test exercises the SAME code path real data
went through.

Requires a live Postgres with migration `0db892e6639a` applied (the
current head)."""

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.application.use_cases.assess_forecast_performance_evidence import (
    AssessForecastPerformanceEvidence,
)
from forex_agent.application.use_cases.build_forecast_performance_population_as_of import (
    BuildForecastPerformancePopulationAsOf,
)
from forex_agent.application.use_cases.calculate_forecast_performance import (
    CalculateForecastPerformance,
)
from forex_agent.application.use_cases.define_forecast_performance_cohort import (
    DefineForecastPerformanceCohort,
)
from forex_agent.application.use_cases.evaluate_structured_forecast import (
    EvaluateStructuredForecast,
)
from forex_agent.application.use_cases.forecast_performance_inspection_support import (
    ForecastPerformanceInspectionMode,
)
from forex_agent.application.use_cases.get_forecast_evaluation_inspection import (
    ForecastEvaluationInspection,
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
from forex_agent.application.use_cases.get_forecast_performance_members import (
    GetForecastPerformanceMembers,
)
from forex_agent.application.use_cases.list_forecast_performance_snapshots import (
    ListForecastPerformanceSnapshots,
)
from forex_agent.application.use_cases.record_forecast_evaluation_protocol import (
    RecordForecastEvaluationProtocol,
)
from forex_agent.application.use_cases.record_forecast_outcome import RecordForecastOutcome
from forex_agent.application.use_cases.record_forecast_outcome_definition import (
    RecordForecastOutcomeDefinition,
)
from forex_agent.application.use_cases.record_forecast_performance_snapshot import (
    RecordForecastPerformanceSnapshot,
)
from forex_agent.application.use_cases.record_source_identity_vintage import (
    RecordSourceIdentityVintage,
)
from forex_agent.application.use_cases.record_structured_forecast import RecordStructuredForecast
from forex_agent.application.use_cases.validate_forecast_outcome_candidate import (
    ForecastOutcomeCandidate,
)
from forex_agent.application.use_cases.validate_structured_forecast_candidate import (
    StructuredForecastCandidate,
)
from forex_agent.domain.evidence_authentication_review import EvidenceAuthenticationReview
from forex_agent.domain.forecast_attribution_kind import ForecastAttributionKind
from forex_agent.domain.forecast_evaluation_metric import ForecastEvaluationMetric
from forex_agent.domain.forecast_evaluation_protocol import ForecastEvaluationProtocol
from forex_agent.domain.forecast_evidence_kind import ForecastEvidenceKind
from forex_agent.domain.forecast_outcome_definition import ForecastOutcomeDefinition
from forex_agent.domain.forecast_performance_cohort_definition import (
    ForecastPerformanceCohortDefinition,
)
from forex_agent.domain.forecast_performance_duplicate_selection_policy import (
    ForecastPerformanceDuplicateSelectionPolicy,
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
from forex_agent.domain.forecast_target_period_kind import ForecastTargetPeriodKind
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.intelligence_source_kind import IntelligenceSourceKind
from forex_agent.domain.outcome_vintage_selection_policy import OutcomeVintageSelectionPolicy
from forex_agent.domain.source_evidence_kind import SourceEvidenceKind
from forex_agent.domain.source_provenance_evidence import SourceProvenanceEvidence
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.forecast_evaluation_repository import (
    SqlAlchemyForecastEvaluationRepository,
)
from forex_agent.infrastructure.db.forecast_outcome_repository import (
    SqlAlchemyForecastOutcomeRepository,
)
from forex_agent.infrastructure.db.forecast_performance_repository import (
    SqlAlchemyForecastPerformanceRepository,
    _cohort_row_values,
)
from forex_agent.infrastructure.db.models.forecast_claim import ForecastClaimRow
from forex_agent.infrastructure.db.models.forecast_evaluation_protocol import (
    ForecastEvaluationProtocolRow,
)
from forex_agent.infrastructure.db.models.forecast_outcome_definition import (
    ForecastOutcomeDefinitionRow,
)
from forex_agent.infrastructure.db.models.forecast_outcome_identity_binding import (
    ForecastOutcomeIdentityBindingRow,
)
from forex_agent.infrastructure.db.models.forecast_outcome_vintage import ForecastOutcomeVintageRow
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
from forex_agent.infrastructure.db.models.intelligence_source import IntelligenceSourceRow
from forex_agent.infrastructure.db.models.source_identity_vintage import SourceIdentityVintageRow
from forex_agent.infrastructure.db.models.structured_forecast_evaluation_vintage import (
    StructuredForecastEvaluationVintageRow,
)
from forex_agent.infrastructure.db.models.structured_forecast_vintage import (
    StructuredForecastVintageRow,
)
from forex_agent.infrastructure.db.session import get_engine
from forex_agent.infrastructure.db.source_registry_repository import (
    SqlAlchemySourceRegistryRepository,
)
from forex_agent.infrastructure.db.structured_forecast_repository import (
    SqlAlchemyStructuredForecastRepository,
)

TEST_PUBLISHER_KEY = "__fx67_inspect_publisher__"
TEST_CLAIM_PREFIX = "__fx67_inspect_claim__"
TEST_DEFINITION_PREFIX = "__fx67_inspect_def__"
TEST_OUTCOME_PREFIX = "__fx67_inspect_outcome__"
TEST_PROTOCOL_PREFIX = "__fx67_inspect_protocol__"
TEST_EVALUATION_PREFIX = "__fx67_inspect_eval__"
TEST_COHORT_PREFIX = "__fx67_inspect_cohort__"
TEST_SNAPSHOT_PREFIX = "__fx67_inspect_snapshot__"

_MODE = ForecastPerformanceInspectionMode.RETROSPECTIVE_RESEARCH


def _ts(hour: int, day: int = 1) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, day, hour, tzinfo=UTC))


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    async with session_factory() as db_session:
        yield db_session

    async with session_factory() as cleanup_session:
        await cleanup_session.execute(
            delete(ForecastPerformanceSnapshotExclusionRow).where(
                ForecastPerformanceSnapshotExclusionRow.snapshot_key.startswith(
                    TEST_SNAPSHOT_PREFIX
                )
            )
        )
        await cleanup_session.execute(
            delete(ForecastPerformanceSnapshotMemberRow).where(
                ForecastPerformanceSnapshotMemberRow.snapshot_key.startswith(TEST_SNAPSHOT_PREFIX)
            )
        )
        await cleanup_session.execute(
            delete(ForecastPerformanceSnapshotRow).where(
                ForecastPerformanceSnapshotRow.snapshot_key.startswith(TEST_SNAPSHOT_PREFIX)
            )
        )
        await cleanup_session.execute(
            delete(ForecastPerformanceMethodologyRow).where(
                ForecastPerformanceMethodologyRow.methodology_key.startswith(TEST_COHORT_PREFIX)
            )
        )
        await cleanup_session.execute(
            delete(ForecastPerformanceCohortRow).where(
                ForecastPerformanceCohortRow.cohort_key.startswith(TEST_COHORT_PREFIX)
            )
        )
        await cleanup_session.execute(
            delete(StructuredForecastEvaluationVintageRow).where(
                StructuredForecastEvaluationVintageRow.evaluation_key.startswith(
                    TEST_EVALUATION_PREFIX
                )
            )
        )
        await cleanup_session.execute(
            delete(ForecastEvaluationProtocolRow).where(
                ForecastEvaluationProtocolRow.protocol_key.startswith(TEST_PROTOCOL_PREFIX)
            )
        )
        await cleanup_session.execute(
            delete(ForecastOutcomeIdentityBindingRow).where(
                ForecastOutcomeIdentityBindingRow.outcome_key.startswith(TEST_OUTCOME_PREFIX)
            )
        )
        await cleanup_session.execute(
            delete(ForecastOutcomeVintageRow).where(
                ForecastOutcomeVintageRow.outcome_key.startswith(TEST_OUTCOME_PREFIX)
            )
        )
        await cleanup_session.execute(
            delete(ForecastOutcomeDefinitionRow).where(
                ForecastOutcomeDefinitionRow.definition_key.startswith(TEST_DEFINITION_PREFIX)
            )
        )
        await cleanup_session.execute(
            delete(StructuredForecastVintageRow).where(
                StructuredForecastVintageRow.claim_key.startswith(TEST_CLAIM_PREFIX)
            )
        )
        await cleanup_session.execute(
            delete(ForecastClaimRow).where(ForecastClaimRow.claim_key.startswith(TEST_CLAIM_PREFIX))
        )
        await cleanup_session.execute(
            delete(SourceIdentityVintageRow).where(
                SourceIdentityVintageRow.source_key == TEST_PUBLISHER_KEY
            )
        )
        await cleanup_session.execute(
            delete(IntelligenceSourceRow).where(
                IntelligenceSourceRow.source_key == TEST_PUBLISHER_KEY
            )
        )
        await cleanup_session.commit()


def _review() -> EvidenceAuthenticationReview:
    return EvidenceAuthenticationReview(
        reviewed_by="FTA research operator",
        review_method="Direct review",
        reviewed_at=_ts(10),
        corroboration_reference="https://example.org/fx67-corroboration",
    )


def _definition(**overrides: object) -> ForecastOutcomeDefinition:
    defaults: dict[str, object] = {
        "definition_key": f"{TEST_DEFINITION_PREFIX}1",
        "version_sequence": 0,
        "target_key": "CA_POLICY_RATE_LEVEL_AFTER_MEETING",
        "outcome_type": ForecastType.NUMERIC_POINT,
        "provider_source_key": TEST_PUBLISHER_KEY,
        "required_source_series_identifier": "BOC-RATE-ANNOUNCEMENT",
        "outcome_vintage_selection_policy": OutcomeVintageSelectionPolicy.FIRST_RELEASE,
        "availability": _ts(9),
        "supporting_definition_reference": "synthetic FX-67 test definition",
    }
    defaults.update(overrides)
    return ForecastOutcomeDefinition(**defaults)  # type: ignore[arg-type]


def _outcome_candidate(**overrides: object) -> ForecastOutcomeCandidate:
    defaults: dict[str, object] = {
        "outcome_key": f"{TEST_OUTCOME_PREFIX}1",
        "availability": _ts(10),
        "definition_key": f"{TEST_DEFINITION_PREFIX}1",
        "definition_version_sequence": 0,
        "target_period_kind": ForecastTargetPeriodKind.POLICY_MEETING,
        "policy_meeting_identifier": "FX67-TEST-MEETING",
        "outcome_type": ForecastType.NUMERIC_POINT,
        "evidence_kind": ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
        "evidence_description": "synthetic decision",
        "document_identifier": "FX67-DOC-1",
        "provenance_mode": ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        "reviewed_by": "FTA research operator",
        "review_method": "Direct review",
        "reviewed_at": _ts(10),
        "numeric_value": Decimal("3.25"),
        "unit": "PERCENT",
    }
    defaults.update(overrides)
    return ForecastOutcomeCandidate(**defaults)  # type: ignore[arg-type]


def _protocol(**overrides: object) -> ForecastEvaluationProtocol:
    defaults: dict[str, object] = {
        "protocol_key": f"{TEST_PROTOCOL_PREFIX}1",
        "version_sequence": 0,
        "supported_forecast_type": ForecastType.NUMERIC_POINT,
        "target_key": "CA_POLICY_RATE_LEVEL_AFTER_MEETING",
        "outcome_definition_key": f"{TEST_DEFINITION_PREFIX}1",
        "outcome_definition_version_sequence": 0,
        "outcome_vintage_selection_policy": OutcomeVintageSelectionPolicy.FIRST_RELEASE,
        "metric": ForecastEvaluationMetric.NUMERIC_ERROR,
        "availability": _ts(9),
        "rationale": "FX-67 synthetic test protocol",
    }
    defaults.update(overrides)
    return ForecastEvaluationProtocol(**defaults)  # type: ignore[arg-type]


def _forecast_candidate(**overrides: object) -> StructuredForecastCandidate:
    defaults: dict[str, object] = {
        "claim_key": f"{TEST_CLAIM_PREFIX}1",
        "availability": _ts(1),
        "algorithm_version": "fx64_v1",
        "forecast_type": ForecastType.NUMERIC_POINT,
        "target_key": "CA_POLICY_RATE_LEVEL_AFTER_MEETING",
        "target_period_kind": ForecastTargetPeriodKind.POLICY_MEETING,
        "policy_meeting_identifier": "FX67-TEST-MEETING",
        "attribution_kind": ForecastAttributionKind.AGGREGATE_SURVEY_CONSENSUS,
        "publisher_source_key": TEST_PUBLISHER_KEY,
        "evidence_kind": ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
        "evidence_description": "synthetic survey forecast",
        "document_identifier": f"{TEST_CLAIM_PREFIX}-doc",
        "provenance_mode": ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        "numeric_value": Decimal("3.75"),
        "unit": "PERCENT",
    }
    defaults.update(overrides)
    return StructuredForecastCandidate(**defaults)  # type: ignore[arg-type]


def _cohort(**overrides: object) -> ForecastPerformanceCohortDefinition:
    defaults: dict[str, object] = {
        "cohort_key": f"{TEST_COHORT_PREFIX}1",
        "version_sequence": 0,
        "attribution_kind": ForecastAttributionKind.AGGREGATE_SURVEY_CONSENSUS,
        "originator_publisher_source_key": TEST_PUBLISHER_KEY,
        "target_key": "CA_POLICY_RATE_LEVEL_AFTER_MEETING",
        "forecast_type": ForecastType.NUMERIC_POINT,
        "horizon_category": "FAD-SAME-MEETING",
        "protocol_key": f"{TEST_PROTOCOL_PREFIX}1",
        "protocol_version_sequence": 0,
        "evaluation_mode": ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        "duplicate_selection_policy": (
            ForecastPerformanceDuplicateSelectionPolicy.EARLIEST_QUALIFYING_ISSUE
        ),
        "availability": _ts(9),
        "rationale": "FX-67 synthetic test cohort",
    }
    defaults.update(overrides)
    return ForecastPerformanceCohortDefinition(**defaults)  # type: ignore[arg-type]


async def _build_pipeline(session: AsyncSession) -> tuple[str, str, str]:
    """Builds one real claim -> outcome -> evaluation -> cohort chain
    through the SAME production use cases real data went through, and
    records one real snapshot. Returns (snapshot_key, evaluation_key,
    claim_key)."""
    registry_repo = SqlAlchemySourceRegistryRepository(session)
    outcome_repo = SqlAlchemyForecastOutcomeRepository(session)
    evaluation_repo = SqlAlchemyForecastEvaluationRepository(session)
    forecast_repo = SqlAlchemyStructuredForecastRepository(session)
    performance_repo = SqlAlchemyForecastPerformanceRepository(session)

    await RecordSourceIdentityVintage(registry_repo)(
        source_key=TEST_PUBLISHER_KEY,
        source_kind=IntelligenceSourceKind.ORGANIZATION,
        registered_at=_ts(8),
        availability=_ts(8),
        algorithm_version="fx62_v1",
        display_name="FX-67 Test Publisher",
        aliases=(),
        authoritative_identifier=None,
        canonical_website=None,
        evidence=SourceProvenanceEvidence(
            evidence_kind=SourceEvidenceKind.ADAPTER_CONFIGURATION, description="test"
        ),
    )
    await RecordForecastOutcomeDefinition(outcome_repo)(_definition())
    await RecordForecastOutcome(outcome_repo)(_outcome_candidate())
    await RecordForecastEvaluationProtocol(evaluation_repo)(_protocol())
    forecast_result = await RecordStructuredForecast(forecast_repo)(
        _forecast_candidate(), registered_at=_ts(1)
    )
    assert forecast_result.vintage is not None

    evaluation_key = f"{TEST_EVALUATION_PREFIX}1"
    eval_result = await EvaluateStructuredForecast(evaluation_repo, outcome_repo)(
        evaluation_key=evaluation_key,
        forecast_vintage=forecast_result.vintage,
        forecast_authentication_review=_review(),
        evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        protocol=_protocol(),
        outcome_key=f"{TEST_OUTCOME_PREFIX}1",
        algorithm_version="fx65_v1",
        availability=_ts(13),
    )
    assert eval_result.vintage is not None

    cohort = _cohort()
    await DefineForecastPerformanceCohort(performance_repo)(cohort)
    methodology = ForecastPerformanceMethodology(
        methodology_key=f"{cohort.cohort_key}-methodology",
        version_sequence=0,
        cohort_key=cohort.cohort_key,
        cohort_version_sequence=0,
        missing_data_policy=ForecastPerformanceMissingDataPolicy.EXCLUDE_FROM_DENOMINATOR,
        algorithm_version="fx66_v1",
        availability=_ts(9),
        rationale="FX-67 synthetic test methodology",
    )
    await performance_repo.add_methodology_version(methodology)

    build_population = BuildForecastPerformancePopulationAsOf(
        evaluation_repo, forecast_repo, outcome_repo
    )
    population = await build_population(cohort, _ts(14))
    assert len(population.accepted) == 1

    numeric, categorical, comparison = CalculateForecastPerformance()(population)
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
    snapshot_key = f"{TEST_SNAPSHOT_PREFIX}1"
    snapshot = ForecastPerformanceSnapshot(
        snapshot_key=snapshot_key,
        revision_sequence=0,
        methodology_key=methodology.methodology_key,
        methodology_version_sequence=0,
        cohort_key=cohort.cohort_key,
        cohort_version_sequence=0,
        evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        members=members,
        exclusions=population.exclusions,
        benchmark_comparison=comparison,
        diagnostics=diagnostics,
        knowledge_cutoff=_ts(14),
        availability=_ts(15),
        algorithm_version="fx66_v1",
        numeric_summary=numeric,
        categorical_summary=categorical,
    )
    result = await RecordForecastPerformanceSnapshot(performance_repo)(
        snapshot, population=population, methodology=methodology
    )
    assert result.outcome.value == "CREATED"
    return snapshot_key, evaluation_key, forecast_result.vintage.claim_key


async def test_real_stored_snapshot_is_independently_inspectable(session: AsyncSession) -> None:
    snapshot_key, _, _ = await _build_pipeline(session)
    performance_repo = SqlAlchemyForecastPerformanceRepository(session)
    evaluation_repo = SqlAlchemyForecastEvaluationRepository(session)
    registry_repo = SqlAlchemySourceRegistryRepository(session)

    get_inspection = GetForecastPerformanceInspection(
        performance_repo, evaluation_repo, registry_repo
    )
    inspection = await get_inspection(snapshot_key, _MODE, _ts(20))

    assert inspection.cohort is not None
    assert inspection.cohort.cohort_key == f"{TEST_COHORT_PREFIX}1"
    assert inspection.snapshot.numeric_summary is not None
    assert inspection.snapshot.numeric_summary.mean_absolute_error == Decimal("0.50")


async def test_member_fk_traversal_resolves_exact_forecast_and_outcome(
    session: AsyncSession,
) -> None:
    snapshot_key, _, _ = await _build_pipeline(session)
    performance_repo = SqlAlchemyForecastPerformanceRepository(session)
    evaluation_repo = SqlAlchemyForecastEvaluationRepository(session)
    forecast_repo = SqlAlchemyStructuredForecastRepository(session)
    outcome_repo = SqlAlchemyForecastOutcomeRepository(session)
    registry_repo = SqlAlchemySourceRegistryRepository(session)

    get_members = GetForecastPerformanceMembers(
        performance_repo, evaluation_repo, forecast_repo, outcome_repo, registry_repo
    )
    page = await get_members(snapshot_key, _MODE, _ts(20), limit=10)

    assert len(page.members) == 1
    member = page.members[0]
    assert isinstance(member, ForecastEvaluationInspection)
    assert member.forecast_vintage.numeric_value == Decimal("3.75")  # type: ignore[union-attr]
    assert member.outcome_vintage.numeric_value == Decimal("3.25")  # type: ignore[union-attr]
    assert member.originator is not None
    assert member.originator.publisher_display_name == "FX-67 Test Publisher"


async def test_pit_mode_filtering_rejects_production_for_research_only_snapshot(
    session: AsyncSession,
) -> None:
    snapshot_key, _, _ = await _build_pipeline(session)
    performance_repo = SqlAlchemyForecastPerformanceRepository(session)
    evaluation_repo = SqlAlchemyForecastEvaluationRepository(session)
    registry_repo = SqlAlchemySourceRegistryRepository(session)
    get_inspection = GetForecastPerformanceInspection(
        performance_repo, evaluation_repo, registry_repo
    )

    with pytest.raises(SnapshotNotVisibleForInspectionError):
        await get_inspection(snapshot_key, ForecastPerformanceInspectionMode.PRODUCTION, _ts(20))


async def test_historical_reconstruction_after_later_evidence_is_appended(
    session: AsyncSession,
) -> None:
    """Appending a LATER evaluation revision against real Postgres
    must not change what an already-recorded snapshot's own member
    inspection shows -- Section 17's own explicit requirement."""
    snapshot_key, evaluation_key, _ = await _build_pipeline(session)
    evaluation_repo = SqlAlchemyForecastEvaluationRepository(session)

    latest = await evaluation_repo.latest_evaluation_vintage(evaluation_key)
    assert latest is not None
    corrected = replace(
        latest,
        revision_sequence=1,
        availability=_ts(10, day=2),
        correction_reason="later correction, must not affect the already-recorded snapshot",
    )
    await evaluation_repo.add_evaluation_vintage(corrected)

    performance_repo = SqlAlchemyForecastPerformanceRepository(session)
    forecast_repo = SqlAlchemyStructuredForecastRepository(session)
    outcome_repo = SqlAlchemyForecastOutcomeRepository(session)
    registry_repo = SqlAlchemySourceRegistryRepository(session)
    get_members = GetForecastPerformanceMembers(
        performance_repo, evaluation_repo, forecast_repo, outcome_repo, registry_repo
    )
    page = await get_members(snapshot_key, _MODE, _ts(20), limit=10)

    member = page.members[0]
    assert isinstance(member, ForecastEvaluationInspection)
    assert member.evaluation.revision_sequence == 0


async def test_no_evidence_table_mutations_from_any_inspection_call(session: AsyncSession) -> None:
    snapshot_key, evaluation_key, claim_key = await _build_pipeline(session)
    performance_repo = SqlAlchemyForecastPerformanceRepository(session)
    evaluation_repo = SqlAlchemyForecastEvaluationRepository(session)
    forecast_repo = SqlAlchemyStructuredForecastRepository(session)
    outcome_repo = SqlAlchemyForecastOutcomeRepository(session)
    registry_repo = SqlAlchemySourceRegistryRepository(session)

    before_eval = await evaluation_repo.list_vintages_for_evaluation(evaluation_key)
    before_forecast = await forecast_repo.list_vintages_for_claim(claim_key)

    await GetForecastPerformanceInspection(performance_repo, evaluation_repo, registry_repo)(
        snapshot_key, _MODE, _ts(20)
    )
    await GetForecastPerformanceMembers(
        performance_repo, evaluation_repo, forecast_repo, outcome_repo, registry_repo
    )(snapshot_key, _MODE, _ts(20), limit=10)
    await GetForecastPerformanceExclusions(performance_repo)(snapshot_key, _MODE, _ts(20), limit=10)
    await GetForecastPerformanceBenchmarkInspection(performance_repo)(snapshot_key, _MODE, _ts(20))

    after_eval = await evaluation_repo.list_vintages_for_evaluation(evaluation_key)
    after_forecast = await forecast_repo.list_vintages_for_claim(claim_key)
    assert before_eval == after_eval
    assert before_forecast == after_forecast


async def test_read_only_inspection_lookups_do_not_commit_unrelated_pending_writes(
    session: AsyncSession,
) -> None:
    """FX-67 Section 16: a mid-call inspection read must not
    prematurely commit an unrelated pending write still sitting on the
    SAME shared session -- mirrors FX-66H.1's own F66-06 pattern."""
    snapshot_key, _, _ = await _build_pipeline(session)
    performance_repo = SqlAlchemyForecastPerformanceRepository(session)
    evaluation_repo = SqlAlchemyForecastEvaluationRepository(session)
    registry_repo = SqlAlchemySourceRegistryRepository(session)

    pending_cohort = _cohort(cohort_key=f"{TEST_COHORT_PREFIX}pending")
    await session.execute(
        insert(ForecastPerformanceCohortRow).values(_cohort_row_values(pending_cohort))
    )

    await GetForecastPerformanceInspection(performance_repo, evaluation_repo, registry_repo)(
        snapshot_key, _MODE, _ts(20)
    )
    await ListForecastPerformanceSnapshots(performance_repo)(limit=50)

    other_session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    async with other_session_factory() as other_session:
        other_repo = SqlAlchemyForecastPerformanceRepository(other_session)
        visible = await other_repo.latest_cohort_version(pending_cohort.cohort_key)
        assert visible is None

    await session.rollback()


async def test_list_snapshots_distinct_keys_real_postgres(session: AsyncSession) -> None:
    snapshot_key, _, _ = await _build_pipeline(session)
    performance_repo = SqlAlchemyForecastPerformanceRepository(session)

    list_snapshots = ListForecastPerformanceSnapshots(performance_repo)
    page = await list_snapshots(cohort_key=f"{TEST_COHORT_PREFIX}1", limit=50)

    assert snapshot_key in page.snapshot_keys
