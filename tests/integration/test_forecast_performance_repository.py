"""FX-66 Section 20.H: real-Postgres integration tests for
`SqlAlchemyForecastPerformanceRepository` -- migration-created
foreign-key integrity, append-only persistence, immutable snapshot
membership (relational child tables), PIT production/research reads,
transaction atomicity of the multi-row snapshot write, and concurrent
idempotency.

Requires a live Postgres with migration `0db892e6639a` applied (the
current head)."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.application.use_cases.build_forecast_performance_population_as_of import (
    ForecastPerformancePopulation,
    ForecastPerformancePopulationMember,
)
from forex_agent.application.use_cases.define_forecast_performance_cohort import (
    DefineForecastPerformanceCohort,
)
from forex_agent.application.use_cases.record_forecast_performance_snapshot import (
    RecordForecastPerformanceSnapshot,
)
from forex_agent.application.use_cases.record_source_identity_vintage import (
    RecordSourceIdentityVintage,
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
from forex_agent.domain.intelligence_source_kind import IntelligenceSourceKind
from forex_agent.domain.source_evidence_kind import SourceEvidenceKind
from forex_agent.domain.source_provenance_evidence import SourceProvenanceEvidence
from forex_agent.domain.structured_forecast_evaluation_vintage import (
    StructuredForecastEvaluationVintage,
)
from forex_agent.domain.structured_forecast_vintage import StructuredForecastVintage
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.forecast_performance_repository import (
    SqlAlchemyForecastPerformanceRepository,
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
from forex_agent.infrastructure.db.models.intelligence_source import IntelligenceSourceRow
from forex_agent.infrastructure.db.models.source_identity_vintage import SourceIdentityVintageRow
from forex_agent.infrastructure.db.session import get_engine
from forex_agent.infrastructure.db.source_registry_repository import (
    SqlAlchemySourceRegistryRepository,
)

TEST_PUBLISHER_KEY = "__fx66_repo_test_publisher__"
TEST_COHORT_PREFIX = "__fx66_repo_test_cohort__"
TEST_SNAPSHOT_PREFIX = "__fx66_repo_test_snapshot__"


def _ts(hour: int, day: int = 1) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, day, hour, tzinfo=UTC))


def _source_evidence() -> SourceProvenanceEvidence:
    return SourceProvenanceEvidence(
        evidence_kind=SourceEvidenceKind.ADAPTER_CONFIGURATION, description="test"
    )


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


@pytest.fixture
def performance_repo(session: AsyncSession) -> SqlAlchemyForecastPerformanceRepository:
    return SqlAlchemyForecastPerformanceRepository(session)


@pytest.fixture
def registry_repo(session: AsyncSession) -> SqlAlchemySourceRegistryRepository:
    return SqlAlchemySourceRegistryRepository(session)


async def _ensure_publisher_registered(registry_repo: SqlAlchemySourceRegistryRepository) -> None:
    record_identity = RecordSourceIdentityVintage(registry_repo)
    await record_identity(
        source_key=TEST_PUBLISHER_KEY,
        source_kind=IntelligenceSourceKind.ORGANIZATION,
        registered_at=_ts(8),
        availability=_ts(8),
        algorithm_version="fx62_v1",
        display_name="Test Publisher Org",
        aliases=(),
        authoritative_identifier=None,
        canonical_website=None,
        evidence=_source_evidence(),
    )


def _cohort(**overrides: object) -> ForecastPerformanceCohortDefinition:
    defaults: dict[str, object] = {
        "cohort_key": f"{TEST_COHORT_PREFIX}1",
        "version_sequence": 0,
        "attribution_kind": ForecastAttributionKind.AGGREGATE_SURVEY_CONSENSUS,
        "originator_publisher_source_key": TEST_PUBLISHER_KEY,
        "target_key": "CA_POLICY_RATE_LEVEL_AFTER_MEETING",
        "forecast_type": ForecastType.NUMERIC_POINT,
        "horizon_category": "SAME-MEETING",
        "protocol_key": "__fx66_nonexistent_protocol__",
        "protocol_version_sequence": 0,
        "evaluation_mode": ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        "duplicate_selection_policy": (
            ForecastPerformanceDuplicateSelectionPolicy.EARLIEST_QUALIFYING_ISSUE
        ),
        "availability": _ts(9),
        "rationale": "integration test cohort",
    }
    defaults.update(overrides)
    return ForecastPerformanceCohortDefinition(**defaults)  # type: ignore[arg-type]


def _member(evaluation_key: str, outcome_key: str) -> ForecastPerformanceSnapshotMember:
    return ForecastPerformanceSnapshotMember(
        evaluation_key=evaluation_key,
        evaluation_revision_sequence=0,
        forecast_claim_key=f"{evaluation_key}-claim",
        forecast_revision_sequence=0,
        outcome_key=outcome_key,
        outcome_revision_sequence=0,
    )


def _population_member(
    evaluation_key: str, outcome_key: str, *, evaluation_availability: UtcTimestamp
) -> ForecastPerformancePopulationMember:
    period = ForecastTargetPeriod(
        period_kind=ForecastTargetPeriodKind.POLICY_MEETING, policy_meeting_identifier="M1"
    )
    evidence = ForecastEvidenceReference(
        evidence_kind=ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
        description="test",
        document_identifier=f"{evaluation_key}-doc",
    )
    review = EvidenceAuthenticationReview(
        reviewed_by="tester", review_method="synthetic", reviewed_at=evaluation_availability
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
            publisher_source_key=TEST_PUBLISHER_KEY,
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
        authentication_review=review,
        provenance_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        numeric_value=Decimal("3.25"),
        unit="PERCENT",
    )
    evaluation = StructuredForecastEvaluationVintage(
        evaluation_key=evaluation_key,
        revision_sequence=0,
        forecast_claim_key=forecast_vintage.claim_key,
        forecast_revision_sequence=0,
        protocol_key="boc-rate-fad-protocol",
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
        forecast_authentication_review=review,
    )
    return ForecastPerformancePopulationMember(evaluation, forecast_vintage, outcome_vintage)


def _population(
    cohort: ForecastPerformanceCohortDefinition,
    *,
    members: tuple[ForecastPerformancePopulationMember, ...] | None = None,
    exclusions: tuple[tuple[str, ForecastPerformanceExclusionReason], ...] = (),
    knowledge_cutoff: UtcTimestamp | None = None,
) -> ForecastPerformancePopulation:
    members = members or (
        _population_member("eval-a", "outcome-a", evaluation_availability=_ts(10)),
        _population_member("eval-b", "outcome-b", evaluation_availability=_ts(10)),
    )
    return ForecastPerformancePopulation(
        cohort=cohort,
        knowledge_cutoff=knowledge_cutoff or _ts(13),
        raw_candidate_count=len(members) + len(exclusions),
        accepted=members,
        exclusions=exclusions,
    )


def _diagnostics(
    accepted_count: int,
    excluded_by_reason: tuple[tuple[ForecastPerformanceExclusionReason, int], ...] = (),
    *,
    pending_revision_count: int = 0,
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
        pending_revision_count=pending_revision_count,
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
        "snapshot_key": f"{TEST_SNAPSHOT_PREFIX}1",
        "revision_sequence": 0,
        "methodology_key": f"{TEST_COHORT_PREFIX}1-methodology",
        "methodology_version_sequence": 0,
        "cohort_key": f"{TEST_COHORT_PREFIX}1",
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


async def test_cohort_fk_requires_existing_protocol(
    registry_repo: SqlAlchemySourceRegistryRepository,
    performance_repo: SqlAlchemyForecastPerformanceRepository,
) -> None:
    await _ensure_publisher_registered(registry_repo)
    with pytest.raises(IntegrityError):
        await performance_repo.add_cohort_version(_cohort())


async def test_cohort_fk_requires_existing_publisher(
    performance_repo: SqlAlchemyForecastPerformanceRepository,
) -> None:
    with pytest.raises(IntegrityError):
        await performance_repo.add_cohort_version(
            _cohort(protocol_key="boc-rate-fad-protocol", protocol_version_sequence=0)
        )


async def test_cohort_round_trip(
    registry_repo: SqlAlchemySourceRegistryRepository,
    performance_repo: SqlAlchemyForecastPerformanceRepository,
) -> None:
    await _ensure_publisher_registered(registry_repo)
    cohort = _cohort(protocol_key="boc-rate-fad-protocol", protocol_version_sequence=0)
    result = await DefineForecastPerformanceCohort(performance_repo)(cohort)

    assert result.outcome.value == "CREATED"
    fetched = await performance_repo.latest_cohort_version(f"{TEST_COHORT_PREFIX}1")
    assert fetched == cohort


async def test_snapshot_persists_members_and_exclusions_relationally(
    session: AsyncSession,
    registry_repo: SqlAlchemySourceRegistryRepository,
    performance_repo: SqlAlchemyForecastPerformanceRepository,
) -> None:
    await _ensure_publisher_registered(registry_repo)
    cohort = _cohort(protocol_key="boc-rate-fad-protocol", protocol_version_sequence=0)
    await DefineForecastPerformanceCohort(performance_repo)(cohort)
    methodology = await _insert_methodology_row(session, cohort.cohort_key, cohort.version_sequence)

    snapshot = _snapshot(
        members=(_member("eval-a", "outcome-a"), _member("eval-b", "outcome-b")),
        exclusions=(("eval-z", ForecastPerformanceExclusionReason.NOT_YET_AVAILABLE),),
    )
    population = _population(
        cohort,
        exclusions=(("eval-z", ForecastPerformanceExclusionReason.NOT_YET_AVAILABLE),),
    )
    result = await RecordForecastPerformanceSnapshot(performance_repo)(
        snapshot, population=population, methodology=methodology
    )
    assert result.outcome.value == "CREATED"

    member_rows = (
        (
            await session.execute(
                select(ForecastPerformanceSnapshotMemberRow).where(
                    ForecastPerformanceSnapshotMemberRow.snapshot_key == snapshot.snapshot_key
                )
            )
        )
        .scalars()
        .all()
    )
    exclusion_rows = (
        (
            await session.execute(
                select(ForecastPerformanceSnapshotExclusionRow).where(
                    ForecastPerformanceSnapshotExclusionRow.snapshot_key == snapshot.snapshot_key
                )
            )
        )
        .scalars()
        .all()
    )
    await session.commit()

    assert len(member_rows) == 2
    assert len(exclusion_rows) == 1
    assert exclusion_rows[0].reason == "NOT_YET_AVAILABLE"

    fetched = await performance_repo.latest_snapshot_vintage(snapshot.snapshot_key)
    assert fetched is not None
    assert len(fetched.members) == 2
    assert len(fetched.exclusions) == 1
    assert fetched == snapshot


async def test_h1_pending_revision_count_round_trips_through_postgres(
    session: AsyncSession,
    registry_repo: SqlAlchemySourceRegistryRepository,
    performance_repo: SqlAlchemyForecastPerformanceRepository,
) -> None:
    """FX-66H (H1): `pending_revision_count` is a real column
    (`diag_pending_revision_count`), not just a transient build-time
    value -- a non-zero value must survive a genuine Postgres write and
    read back unchanged, exactly like every sibling diagnostic field."""
    await _ensure_publisher_registered(registry_repo)
    cohort = _cohort(protocol_key="boc-rate-fad-protocol", protocol_version_sequence=0)
    await DefineForecastPerformanceCohort(performance_repo)(cohort)
    methodology = await _insert_methodology_row(session, cohort.cohort_key, cohort.version_sequence)

    members = (_member("eval-a", "outcome-a"), _member("eval-b", "outcome-b"))
    snapshot = _snapshot(
        members=members,
        diagnostics=_diagnostics(len(members), pending_revision_count=1),
    )
    population = _population(cohort)
    result = await RecordForecastPerformanceSnapshot(performance_repo)(
        snapshot, population=population, methodology=methodology
    )
    assert result.outcome.value == "CREATED"

    fetched = await performance_repo.latest_snapshot_vintage(snapshot.snapshot_key)
    assert fetched is not None
    assert fetched.diagnostics.pending_revision_count == 1
    assert fetched == snapshot


async def test_rejected_snapshot_write_leaves_no_partial_rows(
    session: AsyncSession,
    registry_repo: SqlAlchemySourceRegistryRepository,
    performance_repo: SqlAlchemyForecastPerformanceRepository,
) -> None:
    """A snapshot write that conflicts on `(snapshot_key, revision_
    sequence)` must leave neither the main row NOR any member/
    exclusion rows re-inserted -- atomicity of the multi-statement
    write."""
    await _ensure_publisher_registered(registry_repo)
    cohort = _cohort(protocol_key="boc-rate-fad-protocol", protocol_version_sequence=0)
    await DefineForecastPerformanceCohort(performance_repo)(cohort)
    await _insert_methodology_row(session, cohort.cohort_key, cohort.version_sequence)

    snapshot = _snapshot(members=(_member("eval-a", "outcome-a"),))
    await performance_repo.add_snapshot_vintage(snapshot)

    conflicting = _snapshot(
        members=(_member("eval-a", "outcome-a"), _member("eval-c", "outcome-c"))
    )
    write_result = await performance_repo.add_snapshot_vintage(conflicting)
    assert write_result.inserted is False

    member_rows = (
        (
            await session.execute(
                select(ForecastPerformanceSnapshotMemberRow).where(
                    ForecastPerformanceSnapshotMemberRow.snapshot_key == snapshot.snapshot_key
                )
            )
        )
        .scalars()
        .all()
    )
    await session.commit()
    assert len(member_rows) == 1  # unchanged -- only the original member


async def test_pit_production_vs_research_snapshot_reads(
    session: AsyncSession,
    registry_repo: SqlAlchemySourceRegistryRepository,
    performance_repo: SqlAlchemyForecastPerformanceRepository,
) -> None:
    await _ensure_publisher_registered(registry_repo)
    cohort = _cohort(protocol_key="boc-rate-fad-protocol", protocol_version_sequence=0)
    await DefineForecastPerformanceCohort(performance_repo)(cohort)
    await _insert_methodology_row(session, cohort.cohort_key, cohort.version_sequence)

    research_snapshot = _snapshot(evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH)
    await performance_repo.add_snapshot_vintage(research_snapshot)

    production_result = await performance_repo.latest_production_observed_snapshot_as_of(
        research_snapshot.snapshot_key, _ts(20)
    )
    assert production_result is None

    research_result = await performance_repo.latest_snapshot_as_of_for_research(
        research_snapshot.snapshot_key, _ts(20)
    )
    assert research_result is not None
    assert research_result.evaluation_mode is ForecastProvenanceMode.RETROSPECTIVE_RESEARCH


async def test_concurrent_duplicate_cohort_registration(
    registry_repo: SqlAlchemySourceRegistryRepository,
    performance_repo: SqlAlchemyForecastPerformanceRepository,
) -> None:
    await _ensure_publisher_registered(registry_repo)
    cohort = _cohort(
        cohort_key=f"{TEST_COHORT_PREFIX}concurrent",
        protocol_key="boc-rate-fad-protocol",
        protocol_version_sequence=0,
    )
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)

    async def _register() -> bool:
        async with session_factory() as own_session:
            own_repo = SqlAlchemyForecastPerformanceRepository(own_session)
            result = await own_repo.add_cohort_version(cohort)
            return result.inserted

    results = await asyncio.gather(_register(), _register())

    assert sorted(results) == [False, True]
    fetched = await performance_repo.list_cohort_versions(cohort.cohort_key)
    assert len(fetched) == 1


async def test_concurrent_duplicate_snapshot_recording(
    session: AsyncSession,
    registry_repo: SqlAlchemySourceRegistryRepository,
    performance_repo: SqlAlchemyForecastPerformanceRepository,
) -> None:
    """FX-66H (H3) mandatory test: two independent Postgres sessions
    racing to record the IDENTICAL snapshot (same basis AND payload)
    -- exactly one physically inserts; the other observes `inserted=
    False` (idempotent), and exactly one row survives."""
    await _ensure_publisher_registered(registry_repo)
    cohort = _cohort(
        cohort_key=f"{TEST_COHORT_PREFIX}snap_concurrent",
        protocol_key="boc-rate-fad-protocol",
        protocol_version_sequence=0,
    )
    await DefineForecastPerformanceCohort(performance_repo)(cohort)
    await _insert_methodology_row(session, cohort.cohort_key, cohort.version_sequence)

    snapshot = _snapshot(
        snapshot_key=f"{TEST_SNAPSHOT_PREFIX}concurrent",
        cohort_key=cohort.cohort_key,
        methodology_key=f"{cohort.cohort_key}-methodology",
        members=(_member("eval-a", "outcome-a"),),
    )
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)

    async def _write() -> bool:
        async with session_factory() as own_session:
            own_repo = SqlAlchemyForecastPerformanceRepository(own_session)
            result = await own_repo.add_snapshot_vintage(snapshot)
            return result.inserted

    results = await asyncio.gather(_write(), _write())

    assert sorted(results) == [False, True]
    fetched = await performance_repo.list_vintages_for_snapshot(snapshot.snapshot_key)
    assert len(fetched) == 1


async def _insert_methodology_row(
    session: AsyncSession, cohort_key: str, cohort_version_sequence: int
) -> ForecastPerformanceMethodology:
    methodology = ForecastPerformanceMethodology(
        methodology_key=f"{cohort_key}-methodology",
        version_sequence=0,
        cohort_key=cohort_key,
        cohort_version_sequence=cohort_version_sequence,
        missing_data_policy=ForecastPerformanceMissingDataPolicy.EXCLUDE_FROM_DENOMINATOR,
        algorithm_version="fx66_v1",
        availability=_ts(9),
        rationale="integration test methodology",
    )
    await SqlAlchemyForecastPerformanceRepository(session).add_methodology_version(methodology)
    return methodology
