"""FX-65 Section 8/13: `AssessForecastEvaluationAdmissibility` -- a
PURE function deciding whether ONE forecast vintage can actually be
evaluated. This story's own core principle: a structurally valid,
FX-64-capture-eligible forecast is NOT automatically admissible for
evaluation. Never performs any I/O; takes every input it needs
already resolved by the caller (mirrors `RecordStructuredForecast`'s
own refusal to reach into other repositories).

**FX-65H (H1/H2/H3) corrections, all enforced here**: H1 -- the
resolved outcome's own `definition_key`/`definition_version_sequence`
must match the protocol's own pinned outcome definition (Section 8's
own "outcome definition key"/"outcome definition version" bullets);
H2 -- the evaluation's own `evaluation_availability` must be no
earlier than every input's own FTA-knowledge timestamp (forecast,
protocol, outcome, outcome definition, and both authentication
reviews), using `availability`/`reviewed_at` fields exclusively, NEVER
a publisher-declared release timestamp; H3 -- a `PRODUCTION_OBSERVED`
evaluation requires BOTH the forecast's own vintage AND the resolved
outcome's own vintage to themselves be `PRODUCTION_OBSERVED` (the
original FX-65 check covered only the forecast side)."""

from dataclasses import dataclass

from forex_agent.application.use_cases.resolve_forecast_outcome_as_of import (
    ForecastOutcomeResolutionResult,
)
from forex_agent.domain.evidence_authentication_review import EvidenceAuthenticationReview
from forex_agent.domain.forecast_evaluation_admissibility import ForecastEvaluationAdmissibility
from forex_agent.domain.forecast_evaluation_protocol import ForecastEvaluationProtocol
from forex_agent.domain.forecast_outcome_definition import ForecastOutcomeDefinition
from forex_agent.domain.forecast_outcome_resolution_status import ForecastOutcomeResolutionStatus
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.structured_forecast_vintage import StructuredForecastVintage
from forex_agent.domain.timestamps import UtcTimestamp


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
        outcome_definition: ForecastOutcomeDefinition,
        outcome_resolution: ForecastOutcomeResolutionResult,
        evaluation_availability: UtcTimestamp,
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

        if (
            outcome_vintage.definition_key != protocol.outcome_definition_key
            or outcome_vintage.definition_version_sequence
            != protocol.outcome_definition_version_sequence
        ):
            return ForecastEvaluationAdmissibilityAssessment(
                ForecastEvaluationAdmissibility.PROTOCOL_MISMATCH,
                reason=(
                    f"resolved outcome was captured under definition "
                    f"({outcome_vintage.definition_key!r}, "
                    f"{outcome_vintage.definition_version_sequence}), but protocol "
                    f"{protocol.protocol_key!r} pins definition "
                    f"({protocol.outcome_definition_key!r}, "
                    f"{protocol.outcome_definition_version_sequence})"
                ),
            )

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

        if (
            evaluation_mode is ForecastProvenanceMode.PRODUCTION_OBSERVED
            and outcome_vintage.provenance_mode is not ForecastProvenanceMode.PRODUCTION_OBSERVED
        ):
            return ForecastEvaluationAdmissibilityAssessment(
                ForecastEvaluationAdmissibility.RESEARCH_ONLY,
                reason=(
                    "outcome vintage is RETROSPECTIVE_RESEARCH -- admissible only for a "
                    "RETROSPECTIVE_RESEARCH evaluation, never an implicit promotion into a "
                    "production evaluation"
                ),
            )

        required_inputs = (
            forecast_vintage.availability,
            protocol.availability,
            outcome_vintage.availability,
            outcome_definition.availability,
            forecast_authentication_review.reviewed_at,
            outcome_vintage.authentication_review.reviewed_at,
        )
        latest_input = max(required_inputs, key=lambda ts: ts.value)
        if evaluation_availability.value < latest_input.value:
            return ForecastEvaluationAdmissibilityAssessment(
                ForecastEvaluationAdmissibility.INPUT_NOT_YET_AVAILABLE,
                reason=(
                    f"evaluation_availability={evaluation_availability.value.isoformat()} is "
                    f"earlier than at least one required input's own availability="
                    f"{latest_input.value.isoformat()}"
                ),
            )

        return ForecastEvaluationAdmissibilityAssessment(ForecastEvaluationAdmissibility.ADMISSIBLE)
