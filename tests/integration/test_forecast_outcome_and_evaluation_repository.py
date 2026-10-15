"""FX-65 Section 16.F: real-Postgres integration tests for
`SqlAlchemyForecastOutcomeRepository` and `SqlAlchemyForecastEvaluation
Repository` -- migration-created foreign-key integrity, append-only
persistence, concurrent idempotency, PIT outcome/evaluation reads, and
the "no write survives a rejected candidate/inadmissible evaluation"
guarantee.

Requires a live Postgres with migration `80877afdbe75` applied (the
current head)."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, insert, text
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
from forex_agent.application.use_cases.record_forecast_outcome import (
    ForecastOutcomeIdentityConflictError,
    ForecastOutcomeIdentityImmutabilityError,
    RecordForecastOutcome,
)
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
from forex_agent.domain.forecast_outcome_identity import (
    ForecastOutcomeIdentityBinding,
    canonical_target_period_key,
)
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
    _vintage_row_values,
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


async def test_second_outcome_key_for_the_same_identity_is_rejected(
    registry_repo: SqlAlchemySourceRegistryRepository,
    outcome_repo: SqlAlchemyForecastOutcomeRepository,
) -> None:
    """FX-65H.1 Section 4 test 1/2/3/9: real-Postgres demonstration of
    the outcome-identity-binding invariant -- two outcome_keys sharing
    the identical (definition_key, target_period, unit) cannot both be
    registered, and the rejected attempt writes nothing."""
    await _ensure_publisher_registered(registry_repo)
    await RecordForecastOutcomeDefinition(outcome_repo)(_definition())
    record = RecordForecastOutcome(outcome_repo)
    await record(_outcome_candidate(outcome_key=f"{TEST_OUTCOME_PREFIX}identity-a"))

    with pytest.raises(ForecastOutcomeIdentityConflictError):
        await record(
            _outcome_candidate(
                outcome_key=f"{TEST_OUTCOME_PREFIX}identity-b",
                numeric_value=Decimal("3.10"),
                document_identifier="DOC-OTHER-IDENTITY",
            )
        )

    first_identity_history = await outcome_repo.list_vintages_for_outcome(
        f"{TEST_OUTCOME_PREFIX}identity-a"
    )
    second_identity_history = await outcome_repo.list_vintages_for_outcome(
        f"{TEST_OUTCOME_PREFIX}identity-b"
    )
    assert len(first_identity_history) == 1
    assert second_identity_history == ()


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


async def test_concurrent_different_outcome_keys_same_identity_exactly_one_wins(
    registry_repo: SqlAlchemySourceRegistryRepository,
    outcome_repo: SqlAlchemyForecastOutcomeRepository,
) -> None:
    """FX-65H.2 mandatory test: two DIFFERENT outcome_keys racing to
    claim the SAME measurement identity under two independent real
    Postgres sessions -- unlike FX-65H.1's own read-then-decide check,
    the database's own unique constraint guarantees exactly one
    winner, and the loser leaves no binding or vintage of its own."""
    await _ensure_publisher_registered(registry_repo)
    await RecordForecastOutcomeDefinition(outcome_repo)(
        _definition(definition_key=f"{TEST_DEFINITION_PREFIX}race")
    )
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)

    async def _register(outcome_key: str) -> str:
        async with session_factory() as own_session:
            own_repo = SqlAlchemyForecastOutcomeRepository(own_session)
            candidate = _outcome_candidate(
                outcome_key=outcome_key,
                definition_key=f"{TEST_DEFINITION_PREFIX}race",
                document_identifier=f"DOC-{outcome_key}",
            )
            try:
                result = await RecordForecastOutcome(own_repo)(candidate)
                return result.outcome.value
            except ForecastOutcomeIdentityConflictError:
                return "CONFLICT"

    key_a = f"{TEST_OUTCOME_PREFIX}race-a"
    key_b = f"{TEST_OUTCOME_PREFIX}race-b"
    outcomes = await asyncio.gather(_register(key_a), _register(key_b))

    assert set(outcomes) == {"CREATED", "CONFLICT"}
    history_a = await outcome_repo.list_vintages_for_outcome(key_a)
    history_b = await outcome_repo.list_vintages_for_outcome(key_b)
    winner_history, loser_history = (
        (history_a, history_b) if outcomes[0] == "CREATED" else (history_b, history_a)
    )
    assert len(winner_history) == 1
    assert loser_history == ()


async def test_existing_outcome_key_identity_immutability_enforced_on_real_postgres(
    registry_repo: SqlAlchemySourceRegistryRepository,
    outcome_repo: SqlAlchemyForecastOutcomeRepository,
) -> None:
    """FX-65H.2 (H2), real-Postgres: an already-bound outcome_key
    cannot change the target_period it first registered under, and
    the rejected attempt writes no new vintage."""
    await _ensure_publisher_registered(registry_repo)
    await RecordForecastOutcomeDefinition(outcome_repo)(
        _definition(definition_key=f"{TEST_DEFINITION_PREFIX}immutable")
    )
    record = RecordForecastOutcome(outcome_repo)
    outcome_key = f"{TEST_OUTCOME_PREFIX}immutable"
    await record(
        _outcome_candidate(
            outcome_key=outcome_key, definition_key=f"{TEST_DEFINITION_PREFIX}immutable"
        )
    )

    with pytest.raises(ForecastOutcomeIdentityImmutabilityError):
        await record(
            _outcome_candidate(
                outcome_key=outcome_key,
                definition_key=f"{TEST_DEFINITION_PREFIX}immutable",
                availability=_ts(20),
                policy_meeting_identifier="BOC-2025-01-29",
                document_identifier="DOC-CHANGED-PERIOD",
            )
        )

    history = await outcome_repo.list_vintages_for_outcome(outcome_key)
    assert len(history) == 1


async def test_identity_claim_failure_leaves_no_partial_vintage(
    registry_repo: SqlAlchemySourceRegistryRepository,
    outcome_repo: SqlAlchemyForecastOutcomeRepository,
) -> None:
    """FX-65H.2 (H4), direct repository test: a `claim_outcome_
    identity_and_add_first_vintage` call that loses on the identity
    uniqueness constraint must leave NEITHER a binding row NOR the
    vintage it would have accompanied -- a genuinely atomic failure,
    not a partial write."""
    await _ensure_publisher_registered(registry_repo)
    await RecordForecastOutcomeDefinition(outcome_repo)(
        _definition(definition_key=f"{TEST_DEFINITION_PREFIX}atomic")
    )
    record = RecordForecastOutcome(outcome_repo)
    owner_key = f"{TEST_OUTCOME_PREFIX}atomic-owner"
    await record(
        _outcome_candidate(outcome_key=owner_key, definition_key=f"{TEST_DEFINITION_PREFIX}atomic")
    )

    challenger_binding = await outcome_repo.get_identity_binding_for_key(owner_key)
    assert challenger_binding is not None

    challenger_key = f"{TEST_OUTCOME_PREFIX}atomic-challenger"
    claim_result = await outcome_repo.claim_outcome_identity_and_add_first_vintage(
        ForecastOutcomeIdentityBinding(
            definition_key=challenger_binding.definition_key,
            target_period_key=challenger_binding.target_period_key,
            outcome_type=challenger_binding.outcome_type,
            unit=challenger_binding.unit,
            outcome_key=challenger_key,
        ),
        ForecastOutcomeVintage(
            outcome_key=challenger_key,
            revision_sequence=0,
            definition_key=f"{TEST_DEFINITION_PREFIX}atomic",
            definition_version_sequence=0,
            availability=_ts(10),
            target_period=ForecastTargetPeriod(
                period_kind=ForecastTargetPeriodKind.POLICY_MEETING,
                policy_meeting_identifier="BOC-2024-12-11",
            ),
            outcome_type=ForecastType.NUMERIC_POINT,
            evidence=ForecastEvidenceReference(
                evidence_kind=ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
                description="challenger",
                document_identifier="DOC-CHALLENGER",
            ),
            authentication_review=_review(),
            provenance_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
            numeric_value=Decimal("3.25"),
            unit="PERCENT",
        ),
    )

    assert claim_result.claimed is False
    assert await outcome_repo.list_vintages_for_outcome(challenger_key) == ()
    assert await outcome_repo.get_identity_binding_for_key(challenger_key) is None


async def test_real_boc_identity_binding_matches_canonical_key(
    session: AsyncSession,
) -> None:
    """FX-65H.2 (H3/migration): the real Bank of Canada pilot's own
    pre-existing outcome, backfilled by migration `80877afdbe75`,
    must be bound under the EXACT SAME canonical target-period key
    `domain.forecast_outcome_identity.canonical_target_period_key`
    computes at runtime -- the one real-data regression guard for
    the migration's own SQL-vs-Python format parity."""
    outcome_repo = SqlAlchemyForecastOutcomeRepository(session)
    binding = await outcome_repo.get_identity_binding_for_key("BOC-RATE-DECISION-2024-12-11")
    assert binding is not None
    assert binding.target_period_key == canonical_target_period_key(
        ForecastTargetPeriod(
            period_kind=ForecastTargetPeriodKind.POLICY_MEETING,
            policy_meeting_identifier="BOC-2024-12-11",
        )
    )


async def test_read_only_identity_lookups_do_not_commit_unrelated_pending_writes(
    registry_repo: SqlAlchemySourceRegistryRepository,
    outcome_repo: SqlAlchemyForecastOutcomeRepository,
    session: AsyncSession,
) -> None:
    """FX-65H.3 (H2): `get_identity_binding_for_key`/`get_identity_
    binding_for_identity` must be genuinely read-only -- an uncommitted
    INSERT pending on the SAME session must remain uncommitted (and
    therefore invisible to an independent session) after both lookup
    methods execute against that session."""
    await _ensure_publisher_registered(registry_repo)
    await RecordForecastOutcomeDefinition(outcome_repo)(
        _definition(definition_key=f"{TEST_DEFINITION_PREFIX}txn")
    )
    pending_outcome_key = f"{TEST_OUTCOME_PREFIX}txn-pending"
    pending_vintage = ForecastOutcomeVintage(
        outcome_key=pending_outcome_key,
        revision_sequence=0,
        definition_key=f"{TEST_DEFINITION_PREFIX}txn",
        definition_version_sequence=0,
        availability=_ts(10),
        target_period=ForecastTargetPeriod(
            period_kind=ForecastTargetPeriodKind.POLICY_MEETING,
            policy_meeting_identifier="BOC-2024-12-11",
        ),
        outcome_type=ForecastType.NUMERIC_POINT,
        evidence=ForecastEvidenceReference(
            evidence_kind=ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
            description="pending, never committed",
            document_identifier="DOC-PENDING",
        ),
        authentication_review=_review(),
        provenance_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        numeric_value=Decimal("1"),
        unit="PERCENT",
    )
    await session.execute(
        insert(ForecastOutcomeVintageRow).values(_vintage_row_values(pending_vintage))
    )

    await outcome_repo.get_identity_binding_for_key("__fx65h3_nonexistent_key__")
    await outcome_repo.get_identity_binding_for_identity(
        f"{TEST_DEFINITION_PREFIX}txn",
        canonical_target_period_key(
            ForecastTargetPeriod(
                period_kind=ForecastTargetPeriodKind.POLICY_MEETING,
                policy_meeting_identifier="BOC-2024-12-11",
            )
        ),
        ForecastType.NUMERIC_POINT,
        "PERCENT",
    )

    other_session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    async with other_session_factory() as other_session:
        other_repo = SqlAlchemyForecastOutcomeRepository(other_session)
        visible = await other_repo.list_vintages_for_outcome(pending_outcome_key)
        assert visible == ()

    await session.rollback()


async def test_concurrent_different_keys_same_identity_different_values_exactly_one_wins(
    registry_repo: SqlAlchemySourceRegistryRepository,
    outcome_repo: SqlAlchemyForecastOutcomeRepository,
) -> None:
    """FX-65H.3 (H1), real-Postgres: two DIFFERENT outcome_keys racing
    for the SAME identity, each with a DIFFERENT value -- the database
    constraint still guarantees exactly one owner, and the loser's own
    DIFFERENT content never silently becomes the winner's own."""
    await _ensure_publisher_registered(registry_repo)
    await RecordForecastOutcomeDefinition(outcome_repo)(
        _definition(definition_key=f"{TEST_DEFINITION_PREFIX}race2")
    )
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)

    async def _register(outcome_key: str, numeric_value: Decimal) -> str:
        async with session_factory() as own_session:
            own_repo = SqlAlchemyForecastOutcomeRepository(own_session)
            candidate = _outcome_candidate(
                outcome_key=outcome_key,
                definition_key=f"{TEST_DEFINITION_PREFIX}race2",
                document_identifier=f"DOC-{outcome_key}",
                numeric_value=numeric_value,
            )
            try:
                result = await RecordForecastOutcome(own_repo)(candidate)
                return result.outcome.value
            except ForecastOutcomeIdentityConflictError:
                return "CONFLICT"

    key_a = f"{TEST_OUTCOME_PREFIX}race2-a"
    key_b = f"{TEST_OUTCOME_PREFIX}race2-b"
    outcomes = await asyncio.gather(
        _register(key_a, Decimal("3.25")), _register(key_b, Decimal("3.10"))
    )

    assert set(outcomes) == {"CREATED", "CONFLICT"}
    history_a = await outcome_repo.list_vintages_for_outcome(key_a)
    history_b = await outcome_repo.list_vintages_for_outcome(key_b)
    winner_history, loser_history = (
        (history_a, history_b) if outcomes[0] == "CREATED" else (history_b, history_a)
    )
    assert len(winner_history) == 1
    assert loser_history == ()


async def test_canonical_target_period_key_sql_parity_for_all_period_kinds(
    session: AsyncSession,
) -> None:
    """FX-65H.3 (H3): Python/SQL parity demonstrated for ALL FIVE
    period kinds using SYNTHETIC values -- not merely the one real
    Bank of Canada row (which uses POLICY_MEETING only) -- including a
    SPECIFIC_DATE value with microsecond precision, the exact shape
    the original migration's own SQL formula got wrong."""
    case_sql = """
        CASE target_period_kind
            WHEN 'CALENDAR_YEAR' THEN 'CALENDAR_YEAR:' || calendar_year::text
            WHEN 'CALENDAR_QUARTER' THEN
                'CALENDAR_QUARTER:' || calendar_year::text || ':' || calendar_quarter::text
            WHEN 'CALENDAR_MONTH' THEN
                'CALENDAR_MONTH:' || calendar_year::text || ':'
                    || lpad(calendar_month::text, 2, '0')
            WHEN 'SPECIFIC_DATE' THEN
                'SPECIFIC_DATE:' || to_char(
                    specific_date AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS'
                )
                    || '.' || lpad(
                        (EXTRACT(MICROSECONDS FROM specific_date AT TIME ZONE 'UTC')::bigint
                            % 1000000)::text,
                        6, '0'
                    ) || '+00:00'
            WHEN 'POLICY_MEETING' THEN 'POLICY_MEETING:' || policy_meeting_identifier
        END
    """
    periods = (
        ForecastTargetPeriod(
            period_kind=ForecastTargetPeriodKind.CALENDAR_YEAR, calendar_year=2025
        ),
        ForecastTargetPeriod(
            period_kind=ForecastTargetPeriodKind.CALENDAR_QUARTER,
            calendar_year=2025,
            calendar_quarter=3,
        ),
        ForecastTargetPeriod(
            period_kind=ForecastTargetPeriodKind.CALENDAR_MONTH,
            calendar_year=2025,
            calendar_month=9,
        ),
        ForecastTargetPeriod(
            period_kind=ForecastTargetPeriodKind.SPECIFIC_DATE,
            specific_date=UtcTimestamp(datetime(2024, 12, 11, 12, 30, 45, 654321, tzinfo=UTC)),
        ),
        ForecastTargetPeriod(
            period_kind=ForecastTargetPeriodKind.SPECIFIC_DATE,
            specific_date=UtcTimestamp(datetime(2024, 12, 11, 0, 0, 0, tzinfo=UTC)),
        ),
        ForecastTargetPeriod(
            period_kind=ForecastTargetPeriodKind.POLICY_MEETING,
            policy_meeting_identifier="BOC-2024-12-11",
        ),
    )
    for period in periods:
        row: str = (
            await session.execute(
                text(
                    f"""
                    SELECT ({case_sql}) AS key
                    FROM (VALUES (
                        (:kind)::text, (:year)::int, (:quarter)::int, (:month)::int,
                        (:date)::timestamptz, (:meeting)::text
                    )) AS t(
                        target_period_kind, calendar_year, calendar_quarter, calendar_month,
                        specific_date, policy_meeting_identifier
                    )
                    """
                ),
                {
                    "kind": period.period_kind.value,
                    "year": period.calendar_year,
                    "quarter": period.calendar_quarter,
                    "month": period.calendar_month,
                    "date": period.specific_date.value if period.specific_date else None,
                    "meeting": period.policy_meeting_identifier,
                },
            )
        ).scalar_one()
        await session.rollback()
        assert row == canonical_target_period_key(period)


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

    evaluate = EvaluateStructuredForecast(evaluation_repo, outcome_repo)
    evaluation_key = f"{TEST_EVALUATION_PREFIX}1"
    eval_result = await evaluate(
        evaluation_key=evaluation_key,
        forecast_vintage=forecast_result.vintage,
        forecast_authentication_review=_review(),
        evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        protocol=_protocol(),
        outcome_key=f"{TEST_OUTCOME_PREFIX}1",
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

    evaluate = EvaluateStructuredForecast(
        evaluation_repo, outcome_repo, assess=AssessForecastEvaluationAdmissibility()
    )
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
        outcome_key=f"{TEST_OUTCOME_PREFIX}2",
        algorithm_version="fx65_v1",
        availability=_ts(13),
    )

    assert result.outcome is StructuredForecastEvaluationOutcome.REJECTED
    assert result.admissibility is ForecastEvaluationAdmissibility.UNVERIFIED_SOURCE
    history = await evaluation_repo.list_vintages_for_evaluation(evaluation_key)
    assert history == ()


async def test_list_latest_evaluations_for_protocol_as_of_selects_pit_correct_revision(
    registry_repo: SqlAlchemySourceRegistryRepository,
    outcome_repo: SqlAlchemyForecastOutcomeRepository,
    evaluation_repo: SqlAlchemyForecastEvaluationRepository,
    forecast_repo: SqlAlchemyStructuredForecastRepository,
) -> None:
    """FX-66H (H1), real-Postgres: `list_latest_evaluations_for_
    protocol_as_of` must select revision 0 (available before the
    cutoff) rather than revision 1 (available after), while the
    UNBOUNDED `list_latest_evaluations_for_protocol` still reports
    revision 1 as the overall latest -- exactly the two reads
    `BuildForecastPerformancePopulationAsOf` relies on to never
    exclude a key merely because a later revision exists."""
    await _ensure_publisher_registered(registry_repo)
    await RecordForecastOutcomeDefinition(outcome_repo)(
        _definition(definition_key=f"{TEST_DEFINITION_PREFIX}3")
    )
    await RecordForecastOutcome(outcome_repo)(
        _outcome_candidate(
            outcome_key=f"{TEST_OUTCOME_PREFIX}3", definition_key=f"{TEST_DEFINITION_PREFIX}3"
        )
    )
    protocol_key = f"{TEST_PROTOCOL_PREFIX}3"
    await RecordForecastEvaluationProtocol(evaluation_repo)(
        _protocol(protocol_key=protocol_key, outcome_definition_key=f"{TEST_DEFINITION_PREFIX}3")
    )
    forecast_result = await RecordStructuredForecast(forecast_repo)(
        _forecast_candidate(claim_key=f"{TEST_CLAIM_PREFIX}3"), registered_at=_ts(1)
    )
    assert forecast_result.vintage is not None

    evaluate = EvaluateStructuredForecast(evaluation_repo, outcome_repo)
    evaluation_key = f"{TEST_EVALUATION_PREFIX}3"
    first = await evaluate(
        evaluation_key=evaluation_key,
        forecast_vintage=forecast_result.vintage,
        forecast_authentication_review=_review(),
        evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        protocol=_protocol(
            protocol_key=protocol_key, outcome_definition_key=f"{TEST_DEFINITION_PREFIX}3"
        ),
        outcome_key=f"{TEST_OUTCOME_PREFIX}3",
        algorithm_version="fx65_v1",
        availability=_ts(10),
    )
    assert first.vintage is not None
    assert first.vintage.revision_sequence == 0

    revision_1 = replace(
        first.vintage,
        revision_sequence=1,
        availability=_ts(20),
        correction_reason="later correction, available only after the cutoff under test",
    )
    write_result = await evaluation_repo.add_evaluation_vintage(revision_1)
    assert write_result.inserted is True

    cutoff = _ts(13)
    as_of_bounded = await evaluation_repo.list_latest_evaluations_for_protocol_as_of(
        protocol_key, ForecastProvenanceMode.RETROSPECTIVE_RESEARCH, cutoff
    )
    unbounded = await evaluation_repo.list_latest_evaluations_for_protocol(
        protocol_key, ForecastProvenanceMode.RETROSPECTIVE_RESEARCH
    )

    assert len(as_of_bounded) == 1
    assert as_of_bounded[0].evaluation_key == evaluation_key
    assert as_of_bounded[0].revision_sequence == 0

    assert len(unbounded) == 1
    assert unbounded[0].evaluation_key == evaluation_key
    assert unbounded[0].revision_sequence == 1
