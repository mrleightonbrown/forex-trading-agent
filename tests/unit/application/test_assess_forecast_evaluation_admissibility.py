"""FX-65 Section 8: tests for `AssessForecastEvaluationAdmissibility` --
a structurally valid, FX-64-capture-eligible forecast is NOT
automatically admissible for evaluation (this story's own core
principle).

FX-65H additions: H1 (outcome-definition cross-check), H2 (input-
availability enforcement), H3 (outcome-side production/research mode
compatibility)."""

from datetime import UTC, datetime
from decimal import Decimal

from forex_agent.application.use_cases.assess_forecast_evaluation_admissibility import (
    AssessForecastEvaluationAdmissibility,
    ForecastEvaluationAdmissibilityAssessment,
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
from forex_agent.domain.forecast_outcome_definition import ForecastOutcomeDefinition
from forex_agent.domain.forecast_outcome_resolution_status import ForecastOutcomeResolutionStatus
from forex_agent.domain.forecast_outcome_vintage import ForecastOutcomeVintage
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.forecast_target_period import ForecastTargetPeriod
from forex_agent.domain.forecast_target_period_kind import ForecastTargetPeriodKind
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.outcome_vintage_selection_policy import OutcomeVintageSelectionPolicy
from forex_agent.domain.structured_forecast_vintage import StructuredForecastVintage
from forex_agent.domain.timestamps import UtcTimestamp


def _ts(day: int = 1) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, day, tzinfo=UTC))


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


def _outcome_definition(**overrides: object) -> ForecastOutcomeDefinition:
    defaults: dict[str, object] = {
        "definition_key": "BOC-RATE-OUTCOME",
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


def _review(**overrides: object) -> EvidenceAuthenticationReview:
    defaults: dict[str, object] = {
        "reviewed_by": "FTA research operator",
        "review_method": "Direct review",
        "reviewed_at": _ts(1),
        "corroboration_reference": "https://example.org/corroboration",
    }
    defaults.update(overrides)
    return EvidenceAuthenticationReview(**defaults)  # type: ignore[arg-type]


def _available(vintage: ForecastOutcomeVintage) -> ForecastOutcomeResolutionResult:
    return ForecastOutcomeResolutionResult(
        ForecastOutcomeResolutionStatus.OUTCOME_AVAILABLE, vintage
    )


def _assess(**overrides: object) -> ForecastEvaluationAdmissibilityAssessment:
    assess = AssessForecastEvaluationAdmissibility()
    defaults: dict[str, object] = {
        "forecast_vintage": _forecast_vintage(),
        "forecast_authentication_review": _review(),
        "evaluation_mode": ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        "protocol": _protocol(),
        "outcome_definition": _outcome_definition(),
        "outcome_resolution": _available(_outcome_vintage()),
        "evaluation_availability": _ts(2),
    }
    defaults.update(overrides)
    return assess(**defaults)  # type: ignore[arg-type]


def test_admissible_case() -> None:
    result = _assess()

    assert result.admissibility is ForecastEvaluationAdmissibility.ADMISSIBLE


def test_no_authentication_review_is_unverified_source() -> None:
    result = _assess(forecast_authentication_review=None)

    assert result.admissibility is ForecastEvaluationAdmissibility.UNVERIFIED_SOURCE


def test_review_without_corroboration_is_insufficient_evidence() -> None:
    uncorroborated = EvidenceAuthenticationReview(
        reviewed_by="FTA research operator", review_method="Direct review", reviewed_at=_ts(1)
    )

    result = _assess(forecast_authentication_review=uncorroborated)

    assert result.admissibility is ForecastEvaluationAdmissibility.INSUFFICIENT_EVIDENCE


def test_retrospective_forecast_under_production_mode_is_research_only() -> None:
    result = _assess(
        forecast_vintage=_forecast_vintage(
            provenance_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH
        ),
        evaluation_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED,
        outcome_resolution=_available(
            _outcome_vintage(provenance_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED)
        ),
    )

    assert result.admissibility is ForecastEvaluationAdmissibility.RESEARCH_ONLY


def test_protocol_mismatch_on_target_key() -> None:
    result = _assess(
        protocol=_protocol(
            target_key="CA_REAL_GDP_GROWTH_YOY_YEAR_END",
            outcome_definition_key="BOC-GDP-OUTCOME",
        )
    )

    assert result.admissibility is ForecastEvaluationAdmissibility.PROTOCOL_MISMATCH


def test_not_yet_matured_outcome() -> None:
    result = _assess(
        outcome_resolution=ForecastOutcomeResolutionResult(
            ForecastOutcomeResolutionStatus.NOT_YET_MATURED, None
        )
    )

    assert result.admissibility is ForecastEvaluationAdmissibility.NOT_YET_MATURED


def test_outcome_unavailable() -> None:
    result = _assess(
        outcome_resolution=ForecastOutcomeResolutionResult(
            ForecastOutcomeResolutionStatus.OUTCOME_UNAVAILABLE, None
        )
    )

    assert result.admissibility is ForecastEvaluationAdmissibility.OUTCOME_UNAVAILABLE


def test_ambiguous_target_on_period_mismatch() -> None:
    mismatched_outcome = _outcome_vintage(
        target_period=ForecastTargetPeriod(
            period_kind=ForecastTargetPeriodKind.POLICY_MEETING,
            policy_meeting_identifier="BOC-2025-01-29",
        )
    )

    result = _assess(outcome_resolution=_available(mismatched_outcome))

    assert result.admissibility is ForecastEvaluationAdmissibility.AMBIGUOUS_TARGET


def test_ambiguous_target_on_unit_mismatch() -> None:
    """Section 7's own explicit "never automatically standardize"
    rule -- a unit mismatch between forecast and outcome is refused,
    never silently converted."""
    mismatched_unit_outcome = _outcome_vintage(unit="BASIS_POINTS")

    result = _assess(outcome_resolution=_available(mismatched_unit_outcome))

    assert result.admissibility is ForecastEvaluationAdmissibility.AMBIGUOUS_TARGET


# --- FX-65H H1: outcome-definition cross-check -------------------------------


def test_wrong_outcome_definition_key_is_rejected() -> None:
    wrong_definition_outcome = _outcome_vintage(definition_key="SOME-OTHER-DEFINITION")

    result = _assess(outcome_resolution=_available(wrong_definition_outcome))

    assert result.admissibility is ForecastEvaluationAdmissibility.PROTOCOL_MISMATCH


def test_wrong_outcome_definition_version_is_rejected() -> None:
    wrong_version_outcome = _outcome_vintage(definition_version_sequence=1)

    result = _assess(outcome_resolution=_available(wrong_version_outcome))

    assert result.admissibility is ForecastEvaluationAdmissibility.PROTOCOL_MISMATCH


# --- FX-65H H2: input availability --------------------------------------------


def test_future_outcome_is_rejected() -> None:
    future_outcome = _outcome_vintage(availability=_ts(9))

    result = _assess(outcome_resolution=_available(future_outcome), evaluation_availability=_ts(2))

    assert result.admissibility is ForecastEvaluationAdmissibility.INPUT_NOT_YET_AVAILABLE


def test_future_protocol_is_rejected() -> None:
    future_protocol = _protocol(availability=_ts(9))

    result = _assess(protocol=future_protocol, evaluation_availability=_ts(2))

    assert result.admissibility is ForecastEvaluationAdmissibility.INPUT_NOT_YET_AVAILABLE


def test_future_forecast_vintage_is_rejected() -> None:
    future_forecast = _forecast_vintage(availability=_ts(9))

    result = _assess(forecast_vintage=future_forecast, evaluation_availability=_ts(2))

    assert result.admissibility is ForecastEvaluationAdmissibility.INPUT_NOT_YET_AVAILABLE


def test_future_forecast_authentication_review_is_rejected() -> None:
    future_review = _review(reviewed_at=_ts(9))

    result = _assess(forecast_authentication_review=future_review, evaluation_availability=_ts(2))

    assert result.admissibility is ForecastEvaluationAdmissibility.INPUT_NOT_YET_AVAILABLE


def test_future_outcome_definition_is_rejected() -> None:
    future_definition = _outcome_definition(availability=_ts(9))

    result = _assess(outcome_definition=future_definition, evaluation_availability=_ts(2))

    assert result.admissibility is ForecastEvaluationAdmissibility.INPUT_NOT_YET_AVAILABLE


def test_future_outcome_authentication_review_is_rejected() -> None:
    future_outcome = _outcome_vintage(
        authentication_review=EvidenceAuthenticationReview(
            reviewed_by="FTA research operator", review_method="Direct review", reviewed_at=_ts(9)
        )
    )

    result = _assess(outcome_resolution=_available(future_outcome), evaluation_availability=_ts(2))

    assert result.admissibility is ForecastEvaluationAdmissibility.INPUT_NOT_YET_AVAILABLE


def test_evaluation_availability_equal_to_latest_input_is_admissible() -> None:
    """ "No earlier than" permits equality -- never a strict `<`."""
    result = _assess(evaluation_availability=_ts(1))

    assert result.admissibility is ForecastEvaluationAdmissibility.ADMISSIBLE


# --- FX-65H H3: outcome-side production/research mode compatibility ---------


def test_retrospective_outcome_in_production_evaluation_is_rejected() -> None:
    production_forecast = _forecast_vintage(
        provenance_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED
    )
    retrospective_outcome = _outcome_vintage(
        provenance_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH
    )

    result = _assess(
        forecast_vintage=production_forecast,
        evaluation_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED,
        outcome_resolution=_available(retrospective_outcome),
    )

    assert result.admissibility is ForecastEvaluationAdmissibility.RESEARCH_ONLY


def test_production_outcome_and_forecast_in_production_evaluation_is_admissible() -> None:
    production_forecast = _forecast_vintage(
        provenance_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED
    )
    production_outcome = _outcome_vintage(
        provenance_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED
    )

    result = _assess(
        forecast_vintage=production_forecast,
        evaluation_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED,
        outcome_resolution=_available(production_outcome),
    )

    assert result.admissibility is ForecastEvaluationAdmissibility.ADMISSIBLE


def test_retrospective_evaluation_accepts_either_provenance_mode() -> None:
    """Section 9: retrospective research may consume EITHER
    provenance mode for forecast and outcome."""
    result = _assess(
        forecast_vintage=_forecast_vintage(
            provenance_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED
        ),
        evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        outcome_resolution=_available(
            _outcome_vintage(provenance_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH)
        ),
    )

    assert result.admissibility is ForecastEvaluationAdmissibility.ADMISSIBLE
