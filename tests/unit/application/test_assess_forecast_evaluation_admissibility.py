"""FX-65 Section 8: tests for `AssessForecastEvaluationAdmissibility` --
a structurally valid, FX-64-capture-eligible forecast is NOT
automatically admissible for evaluation (this story's own core
principle)."""

from datetime import UTC, datetime
from decimal import Decimal

from forex_agent.application.use_cases.assess_forecast_evaluation_admissibility import (
    AssessForecastEvaluationAdmissibility,
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


def _ts() -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, tzinfo=UTC))


def _period() -> ForecastTargetPeriod:
    return ForecastTargetPeriod(
        period_kind=ForecastTargetPeriodKind.POLICY_MEETING,
        policy_meeting_identifier="BOC-2024-12-11",
    )


def _forecast_vintage(**overrides: object) -> StructuredForecastVintage:
    defaults: dict[str, object] = {
        "claim_key": "BOC-MPS-2024Q4:CA_POLICY_RATE_LEVEL_AFTER_MEETING:AGGREGATE",
        "revision_sequence": 0,
        "availability": _ts(),
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
        "availability": _ts(),
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
        "availability": _ts(),
        "target_period": _period(),
        "outcome_type": ForecastType.NUMERIC_POINT,
        "evidence": ForecastEvidenceReference(
            evidence_kind=ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
            description="Official decision",
            document_identifier="BOC-PR-2024-12-11",
        ),
        "authentication_review": EvidenceAuthenticationReview(
            reviewed_by="FTA research operator", review_method="Direct review", reviewed_at=_ts()
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
        reviewed_at=_ts(),
        corroboration_reference="https://example.org/corroboration",
    )


def _available(vintage: ForecastOutcomeVintage) -> ForecastOutcomeResolutionResult:
    return ForecastOutcomeResolutionResult(
        ForecastOutcomeResolutionStatus.OUTCOME_AVAILABLE, vintage
    )


def test_admissible_case() -> None:
    assess = AssessForecastEvaluationAdmissibility()

    result = assess(
        forecast_vintage=_forecast_vintage(),
        forecast_authentication_review=_review(),
        evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        protocol=_protocol(),
        outcome_resolution=_available(_outcome_vintage()),
    )

    assert result.admissibility is ForecastEvaluationAdmissibility.ADMISSIBLE


def test_no_authentication_review_is_unverified_source() -> None:
    assess = AssessForecastEvaluationAdmissibility()

    result = assess(
        forecast_vintage=_forecast_vintage(),
        forecast_authentication_review=None,
        evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        protocol=_protocol(),
        outcome_resolution=_available(_outcome_vintage()),
    )

    assert result.admissibility is ForecastEvaluationAdmissibility.UNVERIFIED_SOURCE


def test_review_without_corroboration_is_insufficient_evidence() -> None:
    assess = AssessForecastEvaluationAdmissibility()
    uncorroborated = EvidenceAuthenticationReview(
        reviewed_by="FTA research operator", review_method="Direct review", reviewed_at=_ts()
    )

    result = assess(
        forecast_vintage=_forecast_vintage(),
        forecast_authentication_review=uncorroborated,
        evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        protocol=_protocol(),
        outcome_resolution=_available(_outcome_vintage()),
    )

    assert result.admissibility is ForecastEvaluationAdmissibility.INSUFFICIENT_EVIDENCE


def test_retrospective_forecast_under_production_mode_is_research_only() -> None:
    assess = AssessForecastEvaluationAdmissibility()

    result = assess(
        forecast_vintage=_forecast_vintage(
            provenance_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH
        ),
        forecast_authentication_review=_review(),
        evaluation_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED,
        protocol=_protocol(),
        outcome_resolution=_available(_outcome_vintage()),
    )

    assert result.admissibility is ForecastEvaluationAdmissibility.RESEARCH_ONLY


def test_protocol_mismatch_on_target_key() -> None:
    assess = AssessForecastEvaluationAdmissibility()

    result = assess(
        forecast_vintage=_forecast_vintage(),
        forecast_authentication_review=_review(),
        evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        protocol=_protocol(
            target_key="CA_REAL_GDP_GROWTH_YOY_YEAR_END",
            outcome_definition_key="BOC-GDP-OUTCOME",
        ),
        outcome_resolution=_available(_outcome_vintage()),
    )

    assert result.admissibility is ForecastEvaluationAdmissibility.PROTOCOL_MISMATCH


def test_not_yet_matured_outcome() -> None:
    assess = AssessForecastEvaluationAdmissibility()

    result = assess(
        forecast_vintage=_forecast_vintage(),
        forecast_authentication_review=_review(),
        evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        protocol=_protocol(),
        outcome_resolution=ForecastOutcomeResolutionResult(
            ForecastOutcomeResolutionStatus.NOT_YET_MATURED, None
        ),
    )

    assert result.admissibility is ForecastEvaluationAdmissibility.NOT_YET_MATURED


def test_outcome_unavailable() -> None:
    assess = AssessForecastEvaluationAdmissibility()

    result = assess(
        forecast_vintage=_forecast_vintage(),
        forecast_authentication_review=_review(),
        evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        protocol=_protocol(),
        outcome_resolution=ForecastOutcomeResolutionResult(
            ForecastOutcomeResolutionStatus.OUTCOME_UNAVAILABLE, None
        ),
    )

    assert result.admissibility is ForecastEvaluationAdmissibility.OUTCOME_UNAVAILABLE


def test_ambiguous_target_on_period_mismatch() -> None:
    assess = AssessForecastEvaluationAdmissibility()
    mismatched_outcome = _outcome_vintage(
        target_period=ForecastTargetPeriod(
            period_kind=ForecastTargetPeriodKind.POLICY_MEETING,
            policy_meeting_identifier="BOC-2025-01-29",
        )
    )

    result = assess(
        forecast_vintage=_forecast_vintage(),
        forecast_authentication_review=_review(),
        evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        protocol=_protocol(),
        outcome_resolution=_available(mismatched_outcome),
    )

    assert result.admissibility is ForecastEvaluationAdmissibility.AMBIGUOUS_TARGET


def test_ambiguous_target_on_unit_mismatch() -> None:
    """Section 7's own explicit "never automatically standardize"
    rule -- a unit mismatch between forecast and outcome is refused,
    never silently converted."""
    assess = AssessForecastEvaluationAdmissibility()
    mismatched_unit_outcome = _outcome_vintage(unit="BASIS_POINTS")

    result = assess(
        forecast_vintage=_forecast_vintage(),
        forecast_authentication_review=_review(),
        evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        protocol=_protocol(),
        outcome_resolution=_available(mismatched_unit_outcome),
    )

    assert result.admissibility is ForecastEvaluationAdmissibility.AMBIGUOUS_TARGET
