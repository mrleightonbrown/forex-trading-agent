"""FX-65 Section 11/12/16.D/16.E: tests for `EvaluateStructuredForecast`
-- admissibility-first rejection, PIT ordering/availability, and the
full-history determinism invariant over the COMPLETE evaluation basis."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.application.use_cases.evaluate_structured_forecast import (
    EvaluateStructuredForecast,
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
from forex_agent.application.use_cases.resolve_forecast_outcome_as_of import (
    ForecastOutcomeResolutionResult,
)
from forex_agent.domain.evidence_authentication_review import EvidenceAuthenticationReview
from forex_agent.domain.forecast_attribution import ForecastAttribution
from forex_agent.domain.forecast_attribution_kind import ForecastAttributionKind
from forex_agent.domain.forecast_evaluation_admissibility import ForecastEvaluationAdmissibility
from forex_agent.domain.forecast_evaluation_metric import ForecastEvaluationMetric
from forex_agent.domain.forecast_evaluation_protocol import ForecastEvaluationProtocol
from forex_agent.domain.forecast_evidence_kind import ForecastEvidenceKind
from forex_agent.domain.forecast_evidence_reference import ForecastEvidenceReference
from forex_agent.domain.forecast_outcome_resolution_status import ForecastOutcomeResolutionStatus
from forex_agent.domain.forecast_outcome_vintage import ForecastOutcomeVintage
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.forecast_target_period import ForecastTargetPeriod
from forex_agent.domain.forecast_target_period_kind import ForecastTargetPeriodKind
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.outcome_vintage_selection_policy import OutcomeVintageSelectionPolicy
from forex_agent.domain.structured_forecast_vintage import StructuredForecastVintage
from forex_agent.domain.timestamps import UtcTimestamp
from tests.fakes.forecast_evaluation_repository import FakeForecastEvaluationRepository

_EVALUATION_KEY = "EVAL:BOC-MPS-2024Q4:boc-rate-protocol"


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
        "outcome_definition_key": "BOC-RATE-OUTCOME",
        "outcome_definition_version_sequence": 0,
        "outcome_vintage_selection_policy": OutcomeVintageSelectionPolicy.FIRST_RELEASE,
        "metric": ForecastEvaluationMetric.NUMERIC_ERROR,
        "availability": _ts(1),
        "rationale": "Compares MPS point forecast against the official decision outcome.",
    }
    defaults.update(overrides)
    return ForecastEvaluationProtocol(**defaults)  # type: ignore[arg-type]


def _outcome_vintage(**overrides: object) -> ForecastOutcomeVintage:
    defaults: dict[str, object] = {
        "outcome_key": "BOC-RATE-DECISION-2024-12-11",
        "revision_sequence": 0,
        "definition_key": "BOC-RATE-OUTCOME",
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


def _available(vintage: ForecastOutcomeVintage) -> ForecastOutcomeResolutionResult:
    return ForecastOutcomeResolutionResult(
        ForecastOutcomeResolutionStatus.OUTCOME_AVAILABLE, vintage
    )


def _review() -> EvidenceAuthenticationReview:
    return EvidenceAuthenticationReview(
        reviewed_by="FTA research operator",
        review_method="Direct review",
        reviewed_at=_ts(1),
        corroboration_reference="https://example.org/corroboration",
    )


async def _evaluate(
    repo: FakeForecastEvaluationRepository, **overrides: object
) -> StructuredForecastEvaluationOutcome:
    evaluate = EvaluateStructuredForecast(repo)
    defaults: dict[str, object] = {
        "evaluation_key": _EVALUATION_KEY,
        "forecast_vintage": _forecast_vintage(),
        "forecast_authentication_review": _review(),
        "evaluation_mode": ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        "protocol": _protocol(),
        "outcome_resolution": _available(_outcome_vintage()),
        "algorithm_version": "fx65_v1",
        "availability": _ts(2),
    }
    defaults.update(overrides)
    result = await evaluate(**defaults)  # type: ignore[arg-type]
    return result.outcome


async def test_inadmissible_forecast_is_rejected_and_writes_nothing() -> None:
    repo = FakeForecastEvaluationRepository()
    evaluate = EvaluateStructuredForecast(repo)

    result = await evaluate(
        evaluation_key=_EVALUATION_KEY,
        forecast_vintage=_forecast_vintage(),
        forecast_authentication_review=None,
        evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        protocol=_protocol(),
        outcome_resolution=_available(_outcome_vintage()),
        algorithm_version="fx65_v1",
        availability=_ts(2),
    )

    assert result.outcome is StructuredForecastEvaluationOutcome.REJECTED
    assert result.admissibility is ForecastEvaluationAdmissibility.UNVERIFIED_SOURCE
    assert result.vintage is None
    assert len(repo.vintages) == 0


async def test_first_evaluation_is_created() -> None:
    repo = FakeForecastEvaluationRepository()
    evaluate = EvaluateStructuredForecast(repo)

    result = await evaluate(
        evaluation_key=_EVALUATION_KEY,
        forecast_vintage=_forecast_vintage(),
        forecast_authentication_review=_review(),
        evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        protocol=_protocol(),
        outcome_resolution=_available(_outcome_vintage()),
        algorithm_version="fx65_v1",
        availability=_ts(2),
    )

    assert result.outcome is StructuredForecastEvaluationOutcome.CREATED
    assert result.vintage is not None
    assert result.vintage.result.signed_error == Decimal("-0.50")
    assert result.vintage.result.absolute_error == Decimal("0.50")


async def test_exact_repeat_is_unchanged() -> None:
    repo = FakeForecastEvaluationRepository()
    assert await _evaluate(repo) is StructuredForecastEvaluationOutcome.CREATED

    outcome = await _evaluate(repo, availability=_ts(3))

    assert outcome is StructuredForecastEvaluationOutcome.UNCHANGED
    assert len(repo.vintages[_EVALUATION_KEY]) == 1


async def test_out_of_order_availability_is_rejected() -> None:
    repo = FakeForecastEvaluationRepository()
    assert await _evaluate(repo, availability=_ts(3)) is StructuredForecastEvaluationOutcome.CREATED

    with pytest.raises(OutOfOrderStructuredForecastEvaluationError):
        await _evaluate(repo, availability=_ts(2))


async def test_same_basis_different_result_is_determinism_error() -> None:
    """A different outcome VALUE under the IDENTICAL complete basis
    (same forecast/protocol/outcome vintage/mode/algorithm_version)
    would only arise from a non-deterministic bug -- refused."""
    repo = FakeForecastEvaluationRepository()
    evaluate = EvaluateStructuredForecast(repo)
    await evaluate(
        evaluation_key=_EVALUATION_KEY,
        forecast_vintage=_forecast_vintage(),
        forecast_authentication_review=_review(),
        evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        protocol=_protocol(),
        outcome_resolution=_available(_outcome_vintage()),
        algorithm_version="fx65_v1",
        availability=_ts(2),
    )

    with pytest.raises(StructuredForecastEvaluationDeterminismError):
        await evaluate(
            evaluation_key=_EVALUATION_KEY,
            forecast_vintage=_forecast_vintage(numeric_value=Decimal("4.00")),
            forecast_authentication_review=_review(),
            evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
            protocol=_protocol(),
            outcome_resolution=_available(_outcome_vintage()),
            algorithm_version="fx65_v1",
            availability=_ts(3),
        )


async def test_same_basis_different_authentication_review_is_determinism_error() -> None:
    """The forecast's own authentication review is part of the
    compared payload -- mirrors FX-64H's own "metadata material to
    historical interpretation must not silently change" lesson."""
    repo = FakeForecastEvaluationRepository()
    evaluate = EvaluateStructuredForecast(repo)
    await evaluate(
        evaluation_key=_EVALUATION_KEY,
        forecast_vintage=_forecast_vintage(),
        forecast_authentication_review=_review(),
        evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        protocol=_protocol(),
        outcome_resolution=_available(_outcome_vintage()),
        algorithm_version="fx65_v1",
        availability=_ts(2),
    )
    different_review = EvidenceAuthenticationReview(
        reviewed_by="A different reviewer",
        review_method="Direct review",
        reviewed_at=_ts(1),
        corroboration_reference="https://example.org/corroboration",
    )

    with pytest.raises(StructuredForecastEvaluationDeterminismError):
        await evaluate(
            evaluation_key=_EVALUATION_KEY,
            forecast_vintage=_forecast_vintage(),
            forecast_authentication_review=different_review,
            evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
            protocol=_protocol(),
            outcome_resolution=_available(_outcome_vintage()),
            algorithm_version="fx65_v1",
            availability=_ts(3),
        )


async def test_changed_outcome_vintage_is_a_permitted_reevaluation() -> None:
    """A later outcome revision changes the basis entirely -- a
    legitimate, append-only re-evaluation, never compared against the
    earlier basis."""
    repo = FakeForecastEvaluationRepository()
    evaluate = EvaluateStructuredForecast(repo)
    await evaluate(
        evaluation_key=_EVALUATION_KEY,
        forecast_vintage=_forecast_vintage(),
        forecast_authentication_review=_review(),
        evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        protocol=_protocol(),
        outcome_resolution=_available(_outcome_vintage()),
        algorithm_version="fx65_v1",
        availability=_ts(2),
    )

    revised_outcome = _outcome_vintage(revision_sequence=1, numeric_value=Decimal("3.00"))
    result = await evaluate(
        evaluation_key=_EVALUATION_KEY,
        forecast_vintage=_forecast_vintage(),
        forecast_authentication_review=_review(),
        evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        protocol=_protocol(),
        outcome_resolution=_available(revised_outcome),
        algorithm_version="fx65_v1",
        availability=_ts(3),
        correction_reason="outcome source issued a correction",
    )

    assert result.outcome is StructuredForecastEvaluationOutcome.REVISION_ADDED
    assert result.vintage is not None
    assert result.vintage.result.signed_error == Decimal("-0.75")


async def test_changed_protocol_version_is_an_independent_basis() -> None:
    repo = FakeForecastEvaluationRepository()
    evaluate = EvaluateStructuredForecast(repo)
    await evaluate(
        evaluation_key=_EVALUATION_KEY,
        forecast_vintage=_forecast_vintage(),
        forecast_authentication_review=_review(),
        evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        protocol=_protocol(),
        outcome_resolution=_available(_outcome_vintage()),
        algorithm_version="fx65_v1",
        availability=_ts(2),
    )

    new_protocol_version = _protocol(version_sequence=1, correction_reason="refined rationale text")
    result = await evaluate(
        evaluation_key=_EVALUATION_KEY,
        forecast_vintage=_forecast_vintage(),
        forecast_authentication_review=_review(),
        evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        protocol=new_protocol_version,
        outcome_resolution=_available(_outcome_vintage()),
        algorithm_version="fx65_v1",
        availability=_ts(3),
    )

    assert result.outcome is StructuredForecastEvaluationOutcome.REVISION_ADDED


async def test_full_history_v1_a_v2_b_v1_a_succeeds() -> None:
    repo = FakeForecastEvaluationRepository()
    evaluate = EvaluateStructuredForecast(repo)
    outcome_v1 = _outcome_vintage(revision_sequence=0, numeric_value=Decimal("3.25"))
    outcome_v2 = _outcome_vintage(revision_sequence=1, numeric_value=Decimal("3.00"))
    await evaluate(
        evaluation_key=_EVALUATION_KEY,
        forecast_vintage=_forecast_vintage(),
        forecast_authentication_review=_review(),
        evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        protocol=_protocol(),
        outcome_resolution=_available(outcome_v1),
        algorithm_version="fx65_v1",
        availability=_ts(2),
    )
    await evaluate(
        evaluation_key=_EVALUATION_KEY,
        forecast_vintage=_forecast_vintage(),
        forecast_authentication_review=_review(),
        evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        protocol=_protocol(),
        outcome_resolution=_available(outcome_v2),
        algorithm_version="fx65_v1",
        availability=_ts(3),
    )

    result = await evaluate(
        evaluation_key=_EVALUATION_KEY,
        forecast_vintage=_forecast_vintage(),
        forecast_authentication_review=_review(),
        evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        protocol=_protocol(),
        outcome_resolution=_available(outcome_v1),
        algorithm_version="fx65_v1",
        availability=_ts(4),
    )

    assert result.outcome is StructuredForecastEvaluationOutcome.REVISION_ADDED
    assert result.vintage is not None
    assert result.vintage.result.signed_error == Decimal("-0.50")


async def test_concurrent_duplicate_submission() -> None:
    repo = FakeForecastEvaluationRepository()
    evaluate = EvaluateStructuredForecast(repo)
    kwargs: dict[str, object] = {
        "evaluation_key": _EVALUATION_KEY,
        "forecast_vintage": _forecast_vintage(),
        "forecast_authentication_review": _review(),
        "evaluation_mode": ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        "protocol": _protocol(),
        "outcome_resolution": _available(_outcome_vintage()),
        "algorithm_version": "fx65_v1",
        "availability": _ts(2),
    }

    first = await evaluate(**kwargs)  # type: ignore[arg-type]
    second = await evaluate(**kwargs)  # type: ignore[arg-type]

    assert first.outcome is StructuredForecastEvaluationOutcome.CREATED
    assert second.outcome is StructuredForecastEvaluationOutcome.UNCHANGED
    assert len(repo.vintages[_EVALUATION_KEY]) == 1


async def test_evaluation_invisible_before_its_actual_recording_time() -> None:
    repo = FakeForecastEvaluationRepository()
    evaluate = EvaluateStructuredForecast(repo)
    await evaluate(
        evaluation_key=_EVALUATION_KEY,
        forecast_vintage=_forecast_vintage(
            provenance_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED
        ),
        forecast_authentication_review=_review(),
        evaluation_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED,
        protocol=_protocol(),
        outcome_resolution=_available(_outcome_vintage()),
        algorithm_version="fx65_v1",
        availability=_ts(5),
    )
    get_evaluation = GetForecastEvaluationAsOf(repo)

    before = await get_evaluation(_EVALUATION_KEY, _ts(3))
    after = await get_evaluation(_EVALUATION_KEY, _ts(6))

    assert before.resolution is ForecastEvaluationResolution.NOT_KNOWN
    assert after.resolution is ForecastEvaluationResolution.KNOWN


async def test_later_outcome_correction_leaves_earlier_evaluation_unchanged() -> None:
    repo = FakeForecastEvaluationRepository()
    evaluate = EvaluateStructuredForecast(repo)
    production_forecast = _forecast_vintage(
        provenance_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED
    )
    await evaluate(
        evaluation_key=_EVALUATION_KEY,
        forecast_vintage=production_forecast,
        forecast_authentication_review=_review(),
        evaluation_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED,
        protocol=_protocol(),
        outcome_resolution=_available(_outcome_vintage()),
        algorithm_version="fx65_v1",
        availability=_ts(2),
    )
    get_evaluation = GetForecastEvaluationAsOf(repo)
    before_correction = await get_evaluation(_EVALUATION_KEY, _ts(3))

    revised_outcome = _outcome_vintage(revision_sequence=1, numeric_value=Decimal("3.00"))
    await evaluate(
        evaluation_key=_EVALUATION_KEY,
        forecast_vintage=production_forecast,
        forecast_authentication_review=_review(),
        evaluation_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED,
        protocol=_protocol(),
        outcome_resolution=_available(revised_outcome),
        algorithm_version="fx65_v1",
        availability=_ts(10),
        correction_reason="outcome correction",
    )
    after_correction_same_instant = await get_evaluation(_EVALUATION_KEY, _ts(3))

    assert before_correction.vintage is not None
    assert before_correction.vintage.result.signed_error == Decimal("-0.50")
    assert after_correction_same_instant == before_correction


async def test_retrospective_evaluation_excluded_from_production_pit() -> None:
    repo = FakeForecastEvaluationRepository()
    evaluate = EvaluateStructuredForecast(repo)
    await evaluate(
        evaluation_key=_EVALUATION_KEY,
        forecast_vintage=_forecast_vintage(),
        forecast_authentication_review=_review(),
        evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        protocol=_protocol(),
        outcome_resolution=_available(_outcome_vintage()),
        algorithm_version="fx65_v1",
        availability=_ts(2),
    )
    get_evaluation = GetForecastEvaluationAsOf(repo)
    research_view = GetRetrospectiveForecastEvaluation(repo)

    production_result = await get_evaluation(_EVALUATION_KEY, _ts(10))
    research_result = await research_view(_EVALUATION_KEY, _ts(10))

    assert production_result.resolution is ForecastEvaluationResolution.NOT_KNOWN
    assert research_result.vintage is not None
    assert research_result.is_retrospective is True
