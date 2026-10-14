"""FX-65 Section 11/12/16.D/16.E: tests for `EvaluateStructuredForecast`
-- admissibility-first rejection, PIT ordering/availability, and the
full-history determinism invariant over the COMPLETE evaluation basis.

FX-65H (H1) addition: the outcome is now resolved INTERNALLY (via the
SAME authoritative `ResolveForecastOutcomeAsOf`), from a caller-
supplied `outcome_key` alone -- these tests prove a caller can no
longer inject an outcome vintage the protocol's own policy would not
itself have selected."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.application.use_cases.evaluate_structured_forecast import (
    EvaluateStructuredForecast,
    MissingOutcomeDefinitionVersionError,
    OutOfOrderStructuredForecastEvaluationError,
    StructuredForecastEvaluationDeterminismError,
    StructuredForecastEvaluationOutcome,
)
from forex_agent.application.use_cases.get_forecast_evaluation_as_of import (
    ForecastEvaluationResolution,
    GetForecastEvaluationAsOf,
)
from forex_agent.application.use_cases.get_retrospective_forecast_evaluation import (
    GetRetrospectiveForecastEvaluation,
)
from forex_agent.domain.evidence_authentication_review import EvidenceAuthenticationReview
from forex_agent.domain.forecast_attribution import ForecastAttribution
from forex_agent.domain.forecast_attribution_kind import ForecastAttributionKind
from forex_agent.domain.forecast_evaluation_metric import ForecastEvaluationMetric
from forex_agent.domain.forecast_evaluation_protocol import ForecastEvaluationProtocol
from forex_agent.domain.forecast_evidence_kind import ForecastEvidenceKind
from forex_agent.domain.forecast_evidence_reference import ForecastEvidenceReference
from forex_agent.domain.forecast_outcome_definition import ForecastOutcomeDefinition
from forex_agent.domain.forecast_outcome_vintage import ForecastOutcomeVintage
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.forecast_target_period import ForecastTargetPeriod
from forex_agent.domain.forecast_target_period_kind import ForecastTargetPeriodKind
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.outcome_vintage_selection_policy import OutcomeVintageSelectionPolicy
from forex_agent.domain.structured_forecast_vintage import StructuredForecastVintage
from forex_agent.domain.timestamps import UtcTimestamp
from tests.fakes.forecast_evaluation_repository import FakeForecastEvaluationRepository
from tests.fakes.forecast_outcome_repository import FakeForecastOutcomeRepository

_EVALUATION_KEY = "EVAL:BOC-MPS-2024Q4:boc-rate-protocol"
_OUTCOME_KEY = "BOC-RATE-DECISION-2024-12-11"
_DEFINITION_KEY = "BOC-RATE-OUTCOME"


def _ts(day: int = 1, hour: int = 0) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, day, hour, tzinfo=UTC))


def _period() -> ForecastTargetPeriod:
    return ForecastTargetPeriod(
        period_kind=ForecastTargetPeriodKind.POLICY_MEETING,
        policy_meeting_identifier="BOC-2024-12-11",
    )


def _forecast_vintage(**overrides: object) -> StructuredForecastVintage:
    defaults: dict[str, object] = {
        "claim_key": "BOC-MPS-2024Q4:CA_POLICY_RATE_LEVEL_AFTER_MEETING:AGGREGATE",
        "revision_sequence": 0,
        "availability": _ts(1),
        "algorithm_version": "fx64_v1",
        "forecast_type": ForecastType.NUMERIC_POINT,
        "target_key": "CA_POLICY_RATE_LEVEL_AFTER_MEETING",
        "target_period": _period(),
        "attribution": ForecastAttribution(
            kind=ForecastAttributionKind.AGGREGATE_SURVEY_CONSENSUS,
            publisher_source_key="BANK_OF_CANADA",
        ),
        "provenance_mode": ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        "evidence": ForecastEvidenceReference(
            evidence_kind=ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
            description="MPS Q4 2024",
            document_identifier="BOC-MPS-2024Q4",
        ),
        "numeric_value": Decimal("3.75"),
        "unit": "PERCENT",
    }
    defaults.update(overrides)
    return StructuredForecastVintage(**defaults)  # type: ignore[arg-type]


def _protocol(**overrides: object) -> ForecastEvaluationProtocol:
    defaults: dict[str, object] = {
        "protocol_key": "boc-rate-protocol",
        "version_sequence": 0,
        "supported_forecast_type": ForecastType.NUMERIC_POINT,
        "target_key": "CA_POLICY_RATE_LEVEL_AFTER_MEETING",
        "outcome_definition_key": _DEFINITION_KEY,
        "outcome_definition_version_sequence": 0,
        "outcome_vintage_selection_policy": OutcomeVintageSelectionPolicy.FIRST_RELEASE,
        "metric": ForecastEvaluationMetric.NUMERIC_ERROR,
        "availability": _ts(1),
        "rationale": "Compares MPS point forecast against the official decision outcome.",
    }
    defaults.update(overrides)
    return ForecastEvaluationProtocol(**defaults)  # type: ignore[arg-type]


def _outcome_definition(**overrides: object) -> ForecastOutcomeDefinition:
    defaults: dict[str, object] = {
        "definition_key": _DEFINITION_KEY,
        "version_sequence": 0,
        "target_key": "CA_POLICY_RATE_LEVEL_AFTER_MEETING",
        "outcome_type": ForecastType.NUMERIC_POINT,
        "provider_source_key": "BANK_OF_CANADA",
        "required_source_series_identifier": "BOC-RATE-ANNOUNCEMENT",
        "outcome_vintage_selection_policy": OutcomeVintageSelectionPolicy.FIRST_RELEASE,
        "availability": _ts(1),
        "supporting_definition_reference": "Bank of Canada FAD methodology",
    }
    defaults.update(overrides)
    return ForecastOutcomeDefinition(**defaults)  # type: ignore[arg-type]


def _outcome_vintage(**overrides: object) -> ForecastOutcomeVintage:
    defaults: dict[str, object] = {
        "outcome_key": _OUTCOME_KEY,
        "revision_sequence": 0,
        "definition_key": _DEFINITION_KEY,
        "definition_version_sequence": 0,
        "availability": _ts(1),
        "target_period": _period(),
        "outcome_type": ForecastType.NUMERIC_POINT,
        "evidence": ForecastEvidenceReference(
            evidence_kind=ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
            description="Official decision",
            document_identifier="BOC-PR-2024-12-11",
        ),
        "authentication_review": EvidenceAuthenticationReview(
            reviewed_by="FTA research operator", review_method="Direct review", reviewed_at=_ts(1)
        ),
        "provenance_mode": ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        "numeric_value": Decimal("3.25"),
        "unit": "PERCENT",
    }
    defaults.update(overrides)
    return ForecastOutcomeVintage(**defaults)  # type: ignore[arg-type]


def _review() -> EvidenceAuthenticationReview:
    return EvidenceAuthenticationReview(
        reviewed_by="FTA research operator",
        review_method="Direct review",
        reviewed_at=_ts(1),
        corroboration_reference="https://example.org/corroboration",
    )


def _seeded_outcome_repo(
    *,
    definitions: tuple[ForecastOutcomeDefinition, ...] = (),
    vintages: tuple[ForecastOutcomeVintage, ...] = (),
) -> FakeForecastOutcomeRepository:
    repo = FakeForecastOutcomeRepository()
    for definition in definitions or (_outcome_definition(),):
        repo.definitions.setdefault(definition.definition_key, []).append(definition)
    for vintage in vintages or (_outcome_vintage(),):
        repo.vintages.setdefault(vintage.outcome_key, []).append(vintage)
    return repo


async def _evaluate(
    evaluation_repo: FakeForecastEvaluationRepository,
    outcome_repo: FakeForecastOutcomeRepository,
    **overrides: object,
) -> StructuredForecastEvaluationOutcome:
    evaluate = EvaluateStructuredForecast(evaluation_repo, outcome_repo)
    defaults: dict[str, object] = {
        "evaluation_key": _EVALUATION_KEY,
        "forecast_vintage": _forecast_vintage(),
        "forecast_authentication_review": _review(),
        "evaluation_mode": ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        "protocol": _protocol(),
        "outcome_key": _OUTCOME_KEY,
        "algorithm_version": "fx65_v1",
        "availability": _ts(2),
    }
    defaults.update(overrides)
    result = await evaluate(**defaults)  # type: ignore[arg-type]
    return result.outcome


async def test_first_evaluation_is_created() -> None:
    evaluation_repo = FakeForecastEvaluationRepository()
    outcome_repo = _seeded_outcome_repo()
    evaluate = EvaluateStructuredForecast(evaluation_repo, outcome_repo)

    result = await evaluate(
        evaluation_key=_EVALUATION_KEY,
        forecast_vintage=_forecast_vintage(),
        forecast_authentication_review=_review(),
        evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        protocol=_protocol(),
        outcome_key=_OUTCOME_KEY,
        algorithm_version="fx65_v1",
        availability=_ts(2),
    )

    assert result.outcome is StructuredForecastEvaluationOutcome.CREATED
    assert result.vintage is not None
    assert result.vintage.result.signed_error == Decimal("-0.50")
    assert result.vintage.result.absolute_error == Decimal("0.50")


async def test_inadmissible_forecast_is_rejected_and_writes_nothing() -> None:
    evaluation_repo = FakeForecastEvaluationRepository()
    outcome_repo = _seeded_outcome_repo()

    outcome = await _evaluate(evaluation_repo, outcome_repo, forecast_authentication_review=None)

    assert outcome is StructuredForecastEvaluationOutcome.REJECTED
    assert len(evaluation_repo.vintages) == 0


async def test_exact_repeat_is_unchanged() -> None:
    evaluation_repo = FakeForecastEvaluationRepository()
    outcome_repo = _seeded_outcome_repo()
    assert (
        await _evaluate(evaluation_repo, outcome_repo)
        is StructuredForecastEvaluationOutcome.CREATED
    )

    outcome = await _evaluate(evaluation_repo, outcome_repo, availability=_ts(3))

    assert outcome is StructuredForecastEvaluationOutcome.UNCHANGED
    assert len(evaluation_repo.vintages[_EVALUATION_KEY]) == 1


async def test_out_of_order_availability_is_rejected() -> None:
    evaluation_repo = FakeForecastEvaluationRepository()
    outcome_repo = _seeded_outcome_repo()
    assert (
        await _evaluate(evaluation_repo, outcome_repo, availability=_ts(3))
        is StructuredForecastEvaluationOutcome.CREATED
    )

    with pytest.raises(OutOfOrderStructuredForecastEvaluationError):
        await _evaluate(evaluation_repo, outcome_repo, availability=_ts(2))


async def test_same_basis_different_forecast_value_is_determinism_error() -> None:
    evaluation_repo = FakeForecastEvaluationRepository()
    outcome_repo = _seeded_outcome_repo()
    await _evaluate(evaluation_repo, outcome_repo, availability=_ts(2))

    with pytest.raises(StructuredForecastEvaluationDeterminismError):
        await _evaluate(
            evaluation_repo,
            outcome_repo,
            forecast_vintage=_forecast_vintage(numeric_value=Decimal("4.00")),
            availability=_ts(3),
        )


async def test_same_basis_different_authentication_review_is_determinism_error() -> None:
    """The forecast's own authentication review is part of the
    compared payload -- mirrors FX-64H's own lesson."""
    evaluation_repo = FakeForecastEvaluationRepository()
    outcome_repo = _seeded_outcome_repo()
    await _evaluate(evaluation_repo, outcome_repo, availability=_ts(2))
    different_review = EvidenceAuthenticationReview(
        reviewed_by="A different reviewer",
        review_method="Direct review",
        reviewed_at=_ts(1),
        corroboration_reference="https://example.org/corroboration",
    )

    with pytest.raises(StructuredForecastEvaluationDeterminismError):
        await _evaluate(
            evaluation_repo,
            outcome_repo,
            forecast_authentication_review=different_review,
            availability=_ts(3),
        )


async def test_changed_outcome_vintage_is_a_permitted_reevaluation() -> None:
    """A later outcome revision changes the basis entirely -- a
    legitimate, append-only re-evaluation."""
    evaluation_repo = FakeForecastEvaluationRepository()
    outcome_repo = _seeded_outcome_repo(
        vintages=(
            _outcome_vintage(revision_sequence=0, numeric_value=Decimal("3.25")),
            _outcome_vintage(
                revision_sequence=1, numeric_value=Decimal("3.00"), availability=_ts(1, 12)
            ),
        )
    )
    await _evaluate(
        evaluation_repo,
        outcome_repo,
        protocol=_protocol(
            outcome_vintage_selection_policy=OutcomeVintageSelectionPolicy.FIRST_RELEASE
        ),
        availability=_ts(2),
    )

    fixed_protocol = _protocol(
        version_sequence=1,
        outcome_vintage_selection_policy=OutcomeVintageSelectionPolicy.FIXED_RELEASE_VINTAGE,
        fixed_outcome_revision_sequence=1,
        correction_reason="switch to the corrected release",
    )
    outcome_repo.definitions[_DEFINITION_KEY].append(
        _outcome_definition()
    )  # no-op, already present
    result_outcome = await _evaluate(
        evaluation_repo,
        outcome_repo,
        protocol=fixed_protocol,
        availability=_ts(3),
        correction_reason="outcome source issued a correction",
    )

    assert result_outcome is StructuredForecastEvaluationOutcome.REVISION_ADDED


async def test_concurrent_duplicate_submission() -> None:
    evaluation_repo = FakeForecastEvaluationRepository()
    outcome_repo = _seeded_outcome_repo()

    first = await _evaluate(evaluation_repo, outcome_repo)
    second = await _evaluate(evaluation_repo, outcome_repo)

    assert first is StructuredForecastEvaluationOutcome.CREATED
    assert second is StructuredForecastEvaluationOutcome.UNCHANGED
    assert len(evaluation_repo.vintages[_EVALUATION_KEY]) == 1


async def test_evaluation_invisible_before_its_actual_recording_time() -> None:
    evaluation_repo = FakeForecastEvaluationRepository()
    outcome_repo = _seeded_outcome_repo(
        vintages=(_outcome_vintage(provenance_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED),)
    )
    production_forecast = _forecast_vintage(
        provenance_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED
    )
    await _evaluate(
        evaluation_repo,
        outcome_repo,
        forecast_vintage=production_forecast,
        evaluation_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED,
        availability=_ts(5),
    )
    get_evaluation = GetForecastEvaluationAsOf(evaluation_repo)

    before = await get_evaluation(_EVALUATION_KEY, _ts(3))
    after = await get_evaluation(_EVALUATION_KEY, _ts(6))

    assert before.resolution is ForecastEvaluationResolution.NOT_KNOWN
    assert after.resolution is ForecastEvaluationResolution.KNOWN


async def test_later_outcome_correction_leaves_earlier_evaluation_unchanged() -> None:
    evaluation_repo = FakeForecastEvaluationRepository()
    outcome_repo = _seeded_outcome_repo(
        vintages=(_outcome_vintage(provenance_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED),)
    )
    production_forecast = _forecast_vintage(
        provenance_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED
    )
    await _evaluate(
        evaluation_repo,
        outcome_repo,
        forecast_vintage=production_forecast,
        evaluation_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED,
        availability=_ts(2),
    )
    get_evaluation = GetForecastEvaluationAsOf(evaluation_repo)
    before_correction = await get_evaluation(_EVALUATION_KEY, _ts(3))

    outcome_repo.vintages[_OUTCOME_KEY].append(
        _outcome_vintage(
            revision_sequence=1,
            numeric_value=Decimal("3.00"),
            availability=_ts(1, 12),
            provenance_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED,
        )
    )
    await _evaluate(
        evaluation_repo,
        outcome_repo,
        forecast_vintage=production_forecast,
        evaluation_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED,
        protocol=_protocol(
            outcome_vintage_selection_policy=OutcomeVintageSelectionPolicy.LATEST_AVAILABLE_AS_OF
        ),
        availability=_ts(10),
        correction_reason="outcome correction",
    )
    after_correction_same_instant = await get_evaluation(_EVALUATION_KEY, _ts(3))

    assert before_correction.vintage is not None
    assert before_correction.vintage.result.signed_error == Decimal("-0.50")
    assert after_correction_same_instant == before_correction


async def test_retrospective_evaluation_excluded_from_production_pit() -> None:
    evaluation_repo = FakeForecastEvaluationRepository()
    outcome_repo = _seeded_outcome_repo()
    await _evaluate(evaluation_repo, outcome_repo, availability=_ts(2))
    get_evaluation = GetForecastEvaluationAsOf(evaluation_repo)
    research_view = GetRetrospectiveForecastEvaluation(evaluation_repo)

    production_result = await get_evaluation(_EVALUATION_KEY, _ts(10))
    research_result = await research_view(_EVALUATION_KEY, _ts(10))

    assert production_result.resolution is ForecastEvaluationResolution.NOT_KNOWN
    assert research_result.vintage is not None
    assert research_result.is_retrospective is True


# --- FX-65H H1: the outcome resolver is the ONLY selection mechanism --------


async def test_first_release_policy_ignores_a_later_revision_even_though_one_exists() -> None:
    """Proves the H1 fix structurally: even though a later, "nicer-
    looking" revision exists, a FIRST_RELEASE protocol can NEVER be
    evaluated against anything but revision 0 -- there is no
    parameter through which a caller could inject the later one."""
    evaluation_repo = FakeForecastEvaluationRepository()
    outcome_repo = _seeded_outcome_repo(
        vintages=(
            _outcome_vintage(revision_sequence=0, numeric_value=Decimal("3.25")),
            _outcome_vintage(
                revision_sequence=1, numeric_value=Decimal("3.75"), availability=_ts(1, 12)
            ),
        )
    )

    evaluate = EvaluateStructuredForecast(evaluation_repo, outcome_repo)
    result = await evaluate(
        evaluation_key=_EVALUATION_KEY,
        forecast_vintage=_forecast_vintage(),
        forecast_authentication_review=_review(),
        evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        protocol=_protocol(
            outcome_vintage_selection_policy=OutcomeVintageSelectionPolicy.FIRST_RELEASE
        ),
        outcome_key=_OUTCOME_KEY,
        algorithm_version="fx65_v1",
        availability=_ts(2),
    )

    assert result.vintage is not None
    assert result.vintage.outcome_revision_sequence == 0
    assert result.vintage.result.signed_error == Decimal("-0.50")  # 3.25 - 3.75, NOT 3.75 - 3.75


async def test_fixed_release_vintage_policy_ignores_latest_even_though_one_exists() -> None:
    evaluation_repo = FakeForecastEvaluationRepository()
    outcome_repo = _seeded_outcome_repo(
        vintages=(
            _outcome_vintage(revision_sequence=0, numeric_value=Decimal("3.25")),
            _outcome_vintage(
                revision_sequence=1, numeric_value=Decimal("3.75"), availability=_ts(1, 12)
            ),
        )
    )

    evaluate = EvaluateStructuredForecast(evaluation_repo, outcome_repo)
    result = await evaluate(
        evaluation_key=_EVALUATION_KEY,
        forecast_vintage=_forecast_vintage(),
        forecast_authentication_review=_review(),
        evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        protocol=_protocol(
            outcome_vintage_selection_policy=OutcomeVintageSelectionPolicy.FIXED_RELEASE_VINTAGE,
            fixed_outcome_revision_sequence=0,
        ),
        outcome_key=_OUTCOME_KEY,
        algorithm_version="fx65_v1",
        availability=_ts(2),
    )

    assert result.vintage is not None
    assert result.vintage.outcome_revision_sequence == 0
    assert result.vintage.result.signed_error == Decimal("-0.50")


async def test_wrong_outcome_definition_on_resolved_vintage_is_rejected() -> None:
    """The resolved outcome vintage was captured under a DIFFERENT
    definition than the protocol pins -- rejected (H1)."""
    evaluation_repo = FakeForecastEvaluationRepository()
    outcome_repo = _seeded_outcome_repo(
        vintages=(_outcome_vintage(definition_key="SOME-OTHER-DEFINITION"),)
    )

    outcome = await _evaluate(evaluation_repo, outcome_repo)

    assert outcome is StructuredForecastEvaluationOutcome.REJECTED
    assert len(evaluation_repo.vintages) == 0


async def test_missing_outcome_definition_version_raises() -> None:
    evaluation_repo = FakeForecastEvaluationRepository()
    outcome_repo = _seeded_outcome_repo()
    evaluate = EvaluateStructuredForecast(evaluation_repo, outcome_repo)

    with pytest.raises(MissingOutcomeDefinitionVersionError):
        await evaluate(
            evaluation_key=_EVALUATION_KEY,
            forecast_vintage=_forecast_vintage(),
            forecast_authentication_review=_review(),
            evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
            protocol=_protocol(outcome_definition_version_sequence=99),
            outcome_key=_OUTCOME_KEY,
            algorithm_version="fx65_v1",
            availability=_ts(2),
        )
    assert len(evaluation_repo.vintages) == 0


async def test_future_outcome_definition_rejects_evaluation_without_touching_db() -> None:
    """End-to-end H2 check: a protocol pinning a future-availability
    outcome definition is rejected, and nothing is persisted."""
    evaluation_repo = FakeForecastEvaluationRepository()
    outcome_repo = _seeded_outcome_repo(definitions=(_outcome_definition(availability=_ts(9)),))

    outcome = await _evaluate(evaluation_repo, outcome_repo, availability=_ts(2))

    assert outcome is StructuredForecastEvaluationOutcome.REJECTED
    assert len(evaluation_repo.vintages) == 0
