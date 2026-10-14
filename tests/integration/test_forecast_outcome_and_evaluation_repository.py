"""FX-65 Section 16.F: real-Postgres integration tests for
`SqlAlchemyForecastOutcomeRepository` and `SqlAlchemyForecastEvaluation
Repository` -- migration-created foreign-key integrity, append-only
persistence, concurrent idempotency, PIT outcome/evaluation reads, and
the "no write survives a rejected candidate/inadmissible evaluation"
guarantee.

Requires a live Postgres with migration `0829067d81ae` applied (the
current head)."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.application.use_cases.assess_forecast_evaluation_admissibility import (
    AssessForecastEvaluationAdmissibility,
)
from forex_agent.application.use_cases.evaluate_structured_forecast import (
    EvaluateStructuredForecast,
    StructuredForecastEvaluationOutcome,
)
from forex_agent.application.use_cases.get_forecast_evaluation_as_of import (
    ForecastEvaluationResolution,
    GetForecastEvaluationAsOf,
)
from forex_agent.application.use_cases.get_retrospective_forecast_evaluation import (
    GetRetrospectiveForecastEvaluation,
)
from forex_agent.application.use_cases.record_forecast_evaluation_protocol import (
    RecordForecastEvaluationProtocol,
)
from forex_agent.application.use_cases.record_forecast_outcome import RecordForecastOutcome
from forex_agent.application.use_cases.record_forecast_outcome_definition import (
    RecordForecastOutcomeDefinition,
)
from forex_agent.application.use_cases.record_source_identity_vintage import (
    RecordSourceIdentityVintage,
)
from forex_agent.application.use_cases.record_structured_forecast import RecordStructuredForecast
from forex_agent.application.use_cases.resolve_forecast_outcome_as_of import (
    ResolveForecastOutcomeAsOf,
)
from forex_agent.application.use_cases.validate_forecast_outcome_candidate import (
    ForecastOutcomeCandidate,
)
from forex_agent.application.use_cases.validate_structured_forecast_candidate import (
    StructuredForecastCandidate,
)
from forex_agent.domain.evidence_authentication_review import EvidenceAuthenticationReview
from forex_agent.domain.forecast_attribution_kind import ForecastAttributionKind
from forex_agent.domain.forecast_evaluation_admissibility import ForecastEvaluationAdmissibility
from forex_agent.domain.forecast_evaluation_metric import ForecastEvaluationMetric
from forex_agent.domain.forecast_evaluation_protocol import ForecastEvaluationProtocol
from forex_agent.domain.forecast_evidence_kind import ForecastEvidenceKind
from forex_agent.domain.forecast_evidence_reference import ForecastEvidenceReference
from forex_agent.domain.forecast_outcome_definition import ForecastOutcomeDefinition
from forex_agent.domain.forecast_outcome_resolution_status import ForecastOutcomeResolutionStatus
from forex_agent.domain.forecast_outcome_vintage import ForecastOutcomeVintage
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.forecast_target_period import ForecastTargetPeriod
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
from forex_agent.infrastructure.db.models.forecast_claim import ForecastClaimRow
from forex_agent.infrastructure.db.models.forecast_evaluation_protocol import (
    ForecastEvaluationProtocolRow,
)
from forex_agent.infrastructure.db.models.forecast_outcome_definition import (
    ForecastOutcomeDefinitionRow,
)
from forex_agent.infrastructure.db.models.forecast_outcome_vintage import ForecastOutcomeVintageRow
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

TEST_PUBLISHER_KEY = "__fx65_repo_test_publisher__"
TEST_CLAIM_PREFIX = "__fx65_repo_test_claim__"
TEST_DEFINITION_PREFIX = "__fx65_repo_test_def__"
TEST_OUTCOME_PREFIX = "__fx65_repo_test_outcome__"
TEST_PROTOCOL_PREFIX = "__fx65_repo_test_protocol__"
TEST_EVALUATION_PREFIX = "__fx65_repo_test_eval__"


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


@pytest.fixture
def outcome_repo(session: AsyncSession) -> SqlAlchemyForecastOutcomeRepository:
    return SqlAlchemyForecastOutcomeRepository(session)


@pytest.fixture
def evaluation_repo(session: AsyncSession) -> SqlAlchemyForecastEvaluationRepository:
    return SqlAlchemyForecastEvaluationRepository(session)


@pytest.fixture
def forecast_repo(session: AsyncSession) -> SqlAlchemyStructuredForecastRepository:
    return SqlAlchemyStructuredForecastRepository(session)


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
        "supporting_definition_reference": "Bank of Canada press release methodology",
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
        "policy_meeting_identifier": "BOC-2024-12-11",
        "outcome_type": ForecastType.NUMERIC_POINT,
        "evidence_kind": ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
        "evidence_description": "Official decision",
        "document_identifier": "BOC-PR-2024-12-11",
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
        "rationale": "Compares MPS point forecast against the official decision outcome.",
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
        "policy_meeting_identifier": "BOC-2024-12-11",
        "attribution_kind": ForecastAttributionKind.AGGREGATE_SURVEY_CONSENSUS,
        "publisher_source_key": TEST_PUBLISHER_KEY,
        "evidence_kind": ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
        "evidence_description": "MPS forecast",
        "document_identifier": f"{TEST_CLAIM_PREFIX}-doc",
        "provenance_mode": ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        "numeric_value": Decimal("3.75"),
        "unit": "PERCENT",
    }
    defaults.update(overrides)
    return StructuredForecastCandidate(**defaults)  # type: ignore[arg-type]


def _review() -> EvidenceAuthenticationReview:
    return EvidenceAuthenticationReview(
        reviewed_by="FTA research operator",
        review_method="Direct review",
        reviewed_at=_ts(10),
        corroboration_reference="https://example.org/corroboration",
    )


# --- outcome definitions / outcome vintages ---------------------------------


async def test_outcome_definition_round_trip(
    registry_repo: SqlAlchemySourceRegistryRepository,
    outcome_repo: SqlAlchemyForecastOutcomeRepository,
) -> None:
    await _ensure_publisher_registered(registry_repo)
    record = RecordForecastOutcomeDefinition(outcome_repo)
    result = await record(_definition())

    assert result.outcome.value == "CREATED"
    fetched = await outcome_repo.latest_outcome_definition(f"{TEST_DEFINITION_PREFIX}1")
    assert fetched == _definition()


async def test_outcome_vintage_fk_requires_existing_definition(
    outcome_repo: SqlAlchemyForecastOutcomeRepository,
) -> None:
    orphan = ForecastOutcomeVintage(
        outcome_key=f"{TEST_OUTCOME_PREFIX}orphan",
        revision_sequence=0,
        definition_key="__fx65_nonexistent_definition__",
        definition_version_sequence=0,
        availability=_ts(10),
        target_period=ForecastTargetPeriod(
            period_kind=ForecastTargetPeriodKind.POLICY_MEETING,
            policy_meeting_identifier="BOC-2024-12-11",
        ),
        outcome_type=ForecastType.NUMERIC_POINT,
        evidence=ForecastEvidenceReference(
            evidence_kind=ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
            description="x",
            document_identifier="x",
        ),
        authentication_review=_review(),
        provenance_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        numeric_value=Decimal("1"),
        unit="PERCENT",
    )
    with pytest.raises(IntegrityError):
        await outcome_repo.add_outcome_vintage(orphan)


async def test_outcome_recording_and_pit_resolution(
    registry_repo: SqlAlchemySourceRegistryRepository,
    outcome_repo: SqlAlchemyForecastOutcomeRepository,
) -> None:
    await _ensure_publisher_registered(registry_repo)
    await RecordForecastOutcomeDefinition(outcome_repo)(_definition())
    record = RecordForecastOutcome(outcome_repo)
    created = await record(_outcome_candidate())
    assert created.outcome.value == "CREATED"

    resolve = ResolveForecastOutcomeAsOf(outcome_repo)
    before = await resolve(
        f"{TEST_OUTCOME_PREFIX}1", OutcomeVintageSelectionPolicy.FIRST_RELEASE, _ts(5)
    )
    after = await resolve(
        f"{TEST_OUTCOME_PREFIX}1", OutcomeVintageSelectionPolicy.FIRST_RELEASE, _ts(12)
    )

    assert before.status is ForecastOutcomeResolutionStatus.NOT_YET_MATURED
    assert after.status is ForecastOutcomeResolutionStatus.OUTCOME_AVAILABLE
    assert after.vintage is not None
    assert after.vintage.numeric_value == Decimal("3.25")


async def test_rejected_outcome_candidate_writes_nothing(
    registry_repo: SqlAlchemySourceRegistryRepository,
    outcome_repo: SqlAlchemyForecastOutcomeRepository,
) -> None:
    await _ensure_publisher_registered(registry_repo)
    await RecordForecastOutcomeDefinition(outcome_repo)(_definition())
    record = RecordForecastOutcome(outcome_repo)

    result = await record(_outcome_candidate(unit=None))

    assert result.outcome.value == "REJECTED"
    history = await outcome_repo.list_vintages_for_outcome(f"{TEST_OUTCOME_PREFIX}1")
    assert history == ()


async def test_outcome_append_only_revisions(
    registry_repo: SqlAlchemySourceRegistryRepository,
    outcome_repo: SqlAlchemyForecastOutcomeRepository,
) -> None:
    await _ensure_publisher_registered(registry_repo)
    await RecordForecastOutcomeDefinition(outcome_repo)(_definition())
    record = RecordForecastOutcome(outcome_repo)
    await record(_outcome_candidate())
    await record(
        _outcome_candidate(
            availability=_ts(20), numeric_value=Decimal("3.00"), document_identifier="DOC-2"
        )
    )

    history = await outcome_repo.list_vintages_for_outcome(f"{TEST_OUTCOME_PREFIX}1")
    assert len(history) == 2
    assert {v.revision_sequence for v in history} == {0, 1}


async def test_concurrent_duplicate_outcome_registration(
    registry_repo: SqlAlchemySourceRegistryRepository,
    outcome_repo: SqlAlchemyForecastOutcomeRepository,
) -> None:
    await _ensure_publisher_registered(registry_repo)
    await RecordForecastOutcomeDefinition(outcome_repo)(
        _definition(definition_key=f"{TEST_DEFINITION_PREFIX}concurrent")
    )
    candidate = _outcome_candidate(
        outcome_key=f"{TEST_OUTCOME_PREFIX}concurrent",
        definition_key=f"{TEST_DEFINITION_PREFIX}concurrent",
    )
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)

    async def _register() -> str:
        async with session_factory() as own_session:
            own_repo = SqlAlchemyForecastOutcomeRepository(own_session)
            result = await RecordForecastOutcome(own_repo)(candidate)
            return result.outcome.value

    outcomes = set(await asyncio.gather(_register(), _register()))

    assert outcomes <= {"CREATED", "UNCHANGED"}
    assert "CREATED" in outcomes
    history = await outcome_repo.list_vintages_for_outcome(f"{TEST_OUTCOME_PREFIX}concurrent")
    assert len(history) == 1


# --- evaluation protocols / evaluation vintages -----------------------------


async def test_evaluation_protocol_fk_requires_existing_outcome_definition(
    evaluation_repo: SqlAlchemyForecastEvaluationRepository,
) -> None:
    orphan = _protocol(outcome_definition_key="__fx65_nonexistent_definition__")
    with pytest.raises(IntegrityError):
        await evaluation_repo.add_protocol_version(orphan)


async def test_full_pipeline_evaluation_and_pit_reads(
    registry_repo: SqlAlchemySourceRegistryRepository,
    outcome_repo: SqlAlchemyForecastOutcomeRepository,
    evaluation_repo: SqlAlchemyForecastEvaluationRepository,
    forecast_repo: SqlAlchemyStructuredForecastRepository,
) -> None:
    await _ensure_publisher_registered(registry_repo)
    await RecordForecastOutcomeDefinition(outcome_repo)(_definition())
    await RecordForecastOutcome(outcome_repo)(_outcome_candidate())
    await RecordForecastEvaluationProtocol(evaluation_repo)(_protocol())
    forecast_result = await RecordStructuredForecast(forecast_repo)(
        _forecast_candidate(), registered_at=_ts(1)
    )
    assert forecast_result.vintage is not None

    resolve = ResolveForecastOutcomeAsOf(outcome_repo)
    outcome_resolution = await resolve(
        f"{TEST_OUTCOME_PREFIX}1", OutcomeVintageSelectionPolicy.FIRST_RELEASE, _ts(12)
    )
    assert outcome_resolution.status is ForecastOutcomeResolutionStatus.OUTCOME_AVAILABLE

    evaluate = EvaluateStructuredForecast(evaluation_repo)
    evaluation_key = f"{TEST_EVALUATION_PREFIX}1"
    eval_result = await evaluate(
        evaluation_key=evaluation_key,
        forecast_vintage=forecast_result.vintage,
        forecast_authentication_review=_review(),
        evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        protocol=_protocol(),
        outcome_resolution=outcome_resolution,
        algorithm_version="fx65_v1",
        availability=_ts(13),
    )

    assert eval_result.outcome is StructuredForecastEvaluationOutcome.CREATED
    assert eval_result.admissibility is ForecastEvaluationAdmissibility.ADMISSIBLE
    assert eval_result.vintage is not None
    assert eval_result.vintage.result.signed_error == Decimal("-0.50")

    get_evaluation = GetForecastEvaluationAsOf(evaluation_repo)
    production_read = await get_evaluation(evaluation_key, _ts(20))
    assert production_read.resolution is ForecastEvaluationResolution.NOT_KNOWN

    research_view = GetRetrospectiveForecastEvaluation(evaluation_repo)
    research_read = await research_view(evaluation_key, _ts(20))
    assert research_read.vintage is not None
    assert research_read.is_retrospective is True


async def test_inadmissible_evaluation_writes_nothing(
    registry_repo: SqlAlchemySourceRegistryRepository,
    outcome_repo: SqlAlchemyForecastOutcomeRepository,
    evaluation_repo: SqlAlchemyForecastEvaluationRepository,
    forecast_repo: SqlAlchemyStructuredForecastRepository,
) -> None:
    await _ensure_publisher_registered(registry_repo)
    await RecordForecastOutcomeDefinition(outcome_repo)(
        _definition(definition_key=f"{TEST_DEFINITION_PREFIX}2")
    )
    await RecordForecastOutcome(outcome_repo)(
        _outcome_candidate(
            outcome_key=f"{TEST_OUTCOME_PREFIX}2", definition_key=f"{TEST_DEFINITION_PREFIX}2"
        )
    )
    await RecordForecastEvaluationProtocol(evaluation_repo)(
        _protocol(
            protocol_key=f"{TEST_PROTOCOL_PREFIX}2",
            outcome_definition_key=f"{TEST_DEFINITION_PREFIX}2",
        )
    )
    forecast_result = await RecordStructuredForecast(forecast_repo)(
        _forecast_candidate(claim_key=f"{TEST_CLAIM_PREFIX}2"), registered_at=_ts(1)
    )
    assert forecast_result.vintage is not None

    resolve = ResolveForecastOutcomeAsOf(outcome_repo)
    outcome_resolution = await resolve(
        f"{TEST_OUTCOME_PREFIX}2", OutcomeVintageSelectionPolicy.FIRST_RELEASE, _ts(12)
    )

    evaluate = EvaluateStructuredForecast(evaluation_repo, AssessForecastEvaluationAdmissibility())
    evaluation_key = f"{TEST_EVALUATION_PREFIX}2"
    result = await evaluate(
        evaluation_key=evaluation_key,
        forecast_vintage=forecast_result.vintage,
        forecast_authentication_review=None,  # no review supplied -- UNVERIFIED_SOURCE
        evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        protocol=_protocol(
            protocol_key=f"{TEST_PROTOCOL_PREFIX}2",
            outcome_definition_key=f"{TEST_DEFINITION_PREFIX}2",
        ),
        outcome_resolution=outcome_resolution,
        algorithm_version="fx65_v1",
        availability=_ts(13),
    )

    assert result.outcome is StructuredForecastEvaluationOutcome.REJECTED
    assert result.admissibility is ForecastEvaluationAdmissibility.UNVERIFIED_SOURCE
    history = await evaluation_repo.list_vintages_for_evaluation(evaluation_key)
    assert history == ()
