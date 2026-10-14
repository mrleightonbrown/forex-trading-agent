"""FX-65 Section 8/13: `AssessForecastEvaluationAdmissibility` -- a
PURE function deciding whether ONE forecast vintage can actually be
evaluated. This story's own core principle: a structurally valid,
FX-64-capture-eligible forecast is NOT automatically admissible for
evaluation. Never performs any I/O; takes every input it needs
already resolved by the caller (mirrors `RecordStructuredForecast`'s
own refusal to reach into other repositories)."""

from dataclasses import dataclass

from forex_agent.application.use_cases.resolve_forecast_outcome_as_of import (
    ForecastOutcomeResolutionResult,
)
from forex_agent.domain.evidence_authentication_review import EvidenceAuthenticationReview
from forex_agent.domain.forecast_evaluation_admissibility import ForecastEvaluationAdmissibility
from forex_agent.domain.forecast_evaluation_protocol import ForecastEvaluationProtocol
from forex_agent.domain.forecast_outcome_resolution_status import ForecastOutcomeResolutionStatus
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.structured_forecast_vintage import StructuredForecastVintage


@dataclass(frozen=True, slots=True)
class ForecastEvaluationAdmissibilityAssessment:
    admissibility: ForecastEvaluationAdmissibility
    reason: str | None = None


_RESOLUTION_STATUS_TO_ADMISSIBILITY = {
    ForecastOutcomeResolutionStatus.NOT_YET_MATURED: (
        ForecastEvaluationAdmissibility.NOT_YET_MATURED
    ),
    ForecastOutcomeResolutionStatus.OUTCOME_UNAVAILABLE: (
        ForecastEvaluationAdmissibility.OUTCOME_UNAVAILABLE
    ),
    ForecastOutcomeResolutionStatus.OUTCOME_AMBIGUOUS: (
        ForecastEvaluationAdmissibility.OUTCOME_UNAVAILABLE
    ),
}


class AssessForecastEvaluationAdmissibility:
    def __call__(
        self,
        *,
        forecast_vintage: StructuredForecastVintage,
        forecast_authentication_review: EvidenceAuthenticationReview | None,
        evaluation_mode: ForecastProvenanceMode,
        protocol: ForecastEvaluationProtocol,
        outcome_resolution: ForecastOutcomeResolutionResult,
    ) -> ForecastEvaluationAdmissibilityAssessment:
        if (
            forecast_vintage.forecast_type is not protocol.supported_forecast_type
            or forecast_vintage.target_key != protocol.target_key
        ):
            return ForecastEvaluationAdmissibilityAssessment(
                ForecastEvaluationAdmissibility.PROTOCOL_MISMATCH,
                reason=(
                    f"forecast (type={forecast_vintage.forecast_type.value!r}, "
                    f"target_key={forecast_vintage.target_key!r}) does not match protocol "
                    f"{protocol.protocol_key!r} (type={protocol.supported_forecast_type.value!r}, "
                    f"target_key={protocol.target_key!r})"
                ),
            )

        if forecast_authentication_review is None:
            return ForecastEvaluationAdmissibilityAssessment(
                ForecastEvaluationAdmissibility.UNVERIFIED_SOURCE,
                reason="no EvidenceAuthenticationReview was supplied for this forecast",
            )
        if forecast_authentication_review.corroboration_reference is None:
            return ForecastEvaluationAdmissibilityAssessment(
                ForecastEvaluationAdmissibility.INSUFFICIENT_EVIDENCE,
                reason="forecast's own authentication review carries no corroboration_reference",
            )

        if (
            evaluation_mode is ForecastProvenanceMode.PRODUCTION_OBSERVED
            and forecast_vintage.provenance_mode is not ForecastProvenanceMode.PRODUCTION_OBSERVED
        ):
            return ForecastEvaluationAdmissibilityAssessment(
                ForecastEvaluationAdmissibility.RESEARCH_ONLY,
                reason=(
                    "forecast vintage is RETROSPECTIVE_RESEARCH -- admissible only for a "
                    "RETROSPECTIVE_RESEARCH evaluation, never as a production evaluation"
                ),
            )

        mapped = _RESOLUTION_STATUS_TO_ADMISSIBILITY.get(outcome_resolution.status)
        if mapped is not None:
            return ForecastEvaluationAdmissibilityAssessment(
                mapped, reason=f"outcome resolution status was {outcome_resolution.status.value}"
            )

        outcome_vintage = outcome_resolution.vintage
        assert outcome_vintage is not None
        if outcome_vintage.target_period != forecast_vintage.target_period:
            return ForecastEvaluationAdmissibilityAssessment(
                ForecastEvaluationAdmissibility.AMBIGUOUS_TARGET,
                reason=(
                    f"forecast target_period={forecast_vintage.target_period!r} does not "
                    f"exactly match outcome target_period={outcome_vintage.target_period!r}"
                ),
            )
        if forecast_vintage.unit != outcome_vintage.unit:
            return ForecastEvaluationAdmissibilityAssessment(
                ForecastEvaluationAdmissibility.AMBIGUOUS_TARGET,
                reason=(
                    f"forecast unit={forecast_vintage.unit!r} does not exactly match outcome "
                    f"unit={outcome_vintage.unit!r} -- never automatically standardized "
                    "(Section 7's own explicit prohibition)"
                ),
            )

        return ForecastEvaluationAdmissibilityAssessment(ForecastEvaluationAdmissibility.ADMISSIBLE)
