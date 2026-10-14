"""FX-65 Section 11/12: `EvaluateStructuredForecast` -- evaluates ONE
admissible forecast vintage under ONE protocol against ONE resolved
outcome, and persists the result append-only. Mirrors `RecordStructured
Forecast`'s own overall shape exactly: admissibility is assessed FIRST,
unconditionally (never a general statistical framework -- the
architect's own explicit preference for "a small, rigorously auditable
evaluator"); a non-`ADMISSIBLE` verdict returns a `REJECTED` result
immediately, never reaching the repository.

**Historical determinism (Section 12)**: the determinism basis is the
COMPLETE evaluation basis -- `(forecast_claim_key, forecast_revision_
sequence, protocol_key, protocol_version_sequence, outcome_definition_
key, outcome_definition_version_sequence, outcome_key, outcome_
revision_sequence, evaluation_mode, algorithm_version)`. Because ANY
genuine change (a new outcome revision, a new protocol version, a
different forecast vintage) changes this basis, a basis match implies
the SAME inputs were supplied twice -- the determinism check guards
against a non-deterministic bug in the evaluation algorithm itself,
never against a legitimate data change (which always mints a NEW,
distinct basis, handled as an ordinary `REVISION_ADDED` append,
exactly mirroring FX-64's own "genuinely new evidence is a different
basis, never compared" pattern).

**Precedence**: PIT ordering (the evaluation's own `availability`,
Section 10's third timeline) is checked BEFORE determinism, mirroring
every other append-only use case in this codebase."""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from forex_agent.application.ports.forecast_evaluation_repository import (
    ForecastEvaluationRepository,
)
from forex_agent.application.use_cases.assess_forecast_evaluation_admissibility import (
    AssessForecastEvaluationAdmissibility,
    ForecastEvaluationAdmissibilityAssessment,
)
from forex_agent.application.use_cases.resolve_forecast_outcome_as_of import (
    ForecastOutcomeResolutionResult,
)
from forex_agent.domain.categorical_evaluation_result import CategoricalEvaluationResult
from forex_agent.domain.evidence_authentication_review import EvidenceAuthenticationReview
from forex_agent.domain.forecast_evaluation_admissibility import ForecastEvaluationAdmissibility
from forex_agent.domain.forecast_evaluation_metric import ForecastEvaluationMetric
from forex_agent.domain.forecast_evaluation_protocol import ForecastEvaluationProtocol
from forex_agent.domain.forecast_evaluation_result import ForecastEvaluationResult
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.structured_forecast_evaluation_vintage import (
    StructuredForecastEvaluationVintage,
)
from forex_agent.domain.structured_forecast_vintage import StructuredForecastVintage
from forex_agent.domain.timestamps import UtcTimestamp

_Basis = tuple[str, int, str, int, str, int, str, int, ForecastProvenanceMode, str]
_Payload = tuple[ForecastEvaluationResult, EvidenceAuthenticationReview]


def _basis_of(v: StructuredForecastEvaluationVintage) -> _Basis:
    return (
        v.forecast_claim_key,
        v.forecast_revision_sequence,
        v.protocol_key,
        v.protocol_version_sequence,
        v.outcome_definition_key,
        v.outcome_definition_version_sequence,
        v.outcome_key,
        v.outcome_revision_sequence,
        v.evaluation_mode,
        v.algorithm_version,
    )


def _payload_of(v: StructuredForecastEvaluationVintage) -> _Payload:
    return (v.result, v.forecast_authentication_review)


class StructuredForecastEvaluationOutcome(Enum):
    CREATED = "CREATED"
    REVISION_ADDED = "REVISION_ADDED"
    UNCHANGED = "UNCHANGED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class StructuredForecastEvaluationRecordResult:
    evaluation_key: str
    outcome: StructuredForecastEvaluationOutcome
    admissibility: ForecastEvaluationAdmissibility
    reason: str | None = None
    vintage: StructuredForecastEvaluationVintage | None = None
    """`None` iff `outcome is REJECTED`."""


class OutOfOrderStructuredForecastEvaluationError(Exception):
    def __init__(
        self,
        evaluation_key: str,
        latest_availability: UtcTimestamp,
        incoming_availability: UtcTimestamp,
    ) -> None:
        self.evaluation_key = evaluation_key
        self.latest_availability = latest_availability
        self.incoming_availability = incoming_availability
        super().__init__(
            f"evaluation for evaluation_key={evaluation_key!r} claims availability="
            f"{incoming_availability.value.isoformat()}, earlier than the latest recorded "
            f"vintage's own availability={latest_availability.value.isoformat()} -- refusing "
            "to append a backdated assertion"
        )


class StructuredForecastEvaluationDeterminismError(Exception):
    def __init__(
        self,
        evaluation_key: str,
        basis: _Basis,
        existing_payload: _Payload,
        incoming_payload: _Payload,
    ) -> None:
        self.evaluation_key = evaluation_key
        self.basis = basis
        self.existing_payload = existing_payload
        self.incoming_payload = incoming_payload
        super().__init__(
            f"evaluation_key={evaluation_key!r}, basis={basis!r} already produced a DIFFERENT "
            f"result: existing={existing_payload!r}, incoming={incoming_payload!r} -- the SAME "
            "complete evaluation basis must never produce two different results"
        )


def _compute_result(
    protocol: ForecastEvaluationProtocol,
    forecast_vintage: StructuredForecastVintage,
    outcome_resolution: ForecastOutcomeResolutionResult,
) -> ForecastEvaluationResult:
    outcome_vintage = outcome_resolution.vintage
    assert outcome_vintage is not None
    if protocol.metric is ForecastEvaluationMetric.NUMERIC_ERROR:
        assert forecast_vintage.numeric_value is not None
        assert outcome_vintage.numeric_value is not None
        signed_error: Decimal = outcome_vintage.numeric_value - forecast_vintage.numeric_value
        return ForecastEvaluationResult(
            metric=ForecastEvaluationMetric.NUMERIC_ERROR,
            signed_error=signed_error,
            absolute_error=abs(signed_error),
            unit=outcome_vintage.unit,
        )
    assert forecast_vintage.categorical_outcome is not None
    assert outcome_vintage.categorical_outcome is not None
    categorical_result = (
        CategoricalEvaluationResult.MATCH
        if forecast_vintage.categorical_outcome == outcome_vintage.categorical_outcome
        else CategoricalEvaluationResult.MISMATCH
    )
    return ForecastEvaluationResult(
        metric=ForecastEvaluationMetric.CATEGORICAL_MATCH, categorical_result=categorical_result
    )


class EvaluateStructuredForecast:
    """See the module docstring. Takes every cross-repository input
    ALREADY RESOLVED by the caller (the forecast vintage via FX-64's
    own `GetForecastClaimAsOf`/`GetRetrospectiveForecastResearchView`,
    the outcome resolution via `ResolveForecastOutcomeAsOf`, the
    protocol/outcome-definition via their own repositories) -- this
    use case itself only assesses, computes, and persists."""

    def __init__(
        self,
        repository: ForecastEvaluationRepository,
        assess: AssessForecastEvaluationAdmissibility | None = None,
    ) -> None:
        self._repository = repository
        self._assess = assess or AssessForecastEvaluationAdmissibility()

    async def __call__(
        self,
        *,
        evaluation_key: str,
        forecast_vintage: StructuredForecastVintage,
        forecast_authentication_review: EvidenceAuthenticationReview | None,
        evaluation_mode: ForecastProvenanceMode,
        protocol: ForecastEvaluationProtocol,
        outcome_resolution: ForecastOutcomeResolutionResult,
        algorithm_version: str,
        availability: UtcTimestamp,
        correction_reason: str | None = None,
        dry_run: bool = False,
    ) -> StructuredForecastEvaluationRecordResult:
        assessment: ForecastEvaluationAdmissibilityAssessment = self._assess(
            forecast_vintage=forecast_vintage,
            forecast_authentication_review=forecast_authentication_review,
            evaluation_mode=evaluation_mode,
            protocol=protocol,
            outcome_resolution=outcome_resolution,
        )
        if assessment.admissibility is not ForecastEvaluationAdmissibility.ADMISSIBLE:
            return StructuredForecastEvaluationRecordResult(
                evaluation_key=evaluation_key,
                outcome=StructuredForecastEvaluationOutcome.REJECTED,
                admissibility=assessment.admissibility,
                reason=assessment.reason,
            )
        assert forecast_authentication_review is not None
        outcome_vintage = outcome_resolution.vintage
        assert outcome_vintage is not None

        latest = await self._repository.latest_evaluation_vintage(evaluation_key)
        if latest is not None and availability.value < latest.availability.value:
            raise OutOfOrderStructuredForecastEvaluationError(
                evaluation_key, latest.availability, availability
            )

        result = _compute_result(protocol, forecast_vintage, outcome_resolution)
        incoming_basis: _Basis = (
            forecast_vintage.claim_key,
            forecast_vintage.revision_sequence,
            protocol.protocol_key,
            protocol.version_sequence,
            protocol.outcome_definition_key,
            protocol.outcome_definition_version_sequence,
            outcome_vintage.outcome_key,
            outcome_vintage.revision_sequence,
            evaluation_mode,
            algorithm_version,
        )
        incoming_payload: _Payload = (result, forecast_authentication_review)

        history = await self._repository.list_vintages_for_evaluation(evaluation_key)
        for historical in history:
            if _basis_of(historical) != incoming_basis:
                continue
            if _payload_of(historical) != incoming_payload:
                raise StructuredForecastEvaluationDeterminismError(
                    evaluation_key, incoming_basis, _payload_of(historical), incoming_payload
                )

        if (
            latest is not None
            and _basis_of(latest) == incoming_basis
            and _payload_of(latest) == incoming_payload
        ):
            return StructuredForecastEvaluationRecordResult(
                evaluation_key=evaluation_key,
                outcome=StructuredForecastEvaluationOutcome.UNCHANGED,
                admissibility=ForecastEvaluationAdmissibility.ADMISSIBLE,
                vintage=latest,
            )

        next_revision = 0 if latest is None else latest.revision_sequence + 1
        new_vintage = StructuredForecastEvaluationVintage(
            evaluation_key=evaluation_key,
            revision_sequence=next_revision,
            forecast_claim_key=forecast_vintage.claim_key,
            forecast_revision_sequence=forecast_vintage.revision_sequence,
            protocol_key=protocol.protocol_key,
            protocol_version_sequence=protocol.version_sequence,
            outcome_definition_key=protocol.outcome_definition_key,
            outcome_definition_version_sequence=protocol.outcome_definition_version_sequence,
            outcome_key=outcome_vintage.outcome_key,
            outcome_revision_sequence=outcome_vintage.revision_sequence,
            evaluation_mode=evaluation_mode,
            algorithm_version=algorithm_version,
            availability=availability,
            result=result,
            forecast_authentication_review=forecast_authentication_review,
            correction_reason=correction_reason,
        )
        outcome_label = (
            StructuredForecastEvaluationOutcome.CREATED
            if latest is None
            else StructuredForecastEvaluationOutcome.REVISION_ADDED
        )
        if dry_run:
            return StructuredForecastEvaluationRecordResult(
                evaluation_key=evaluation_key,
                outcome=outcome_label,
                admissibility=ForecastEvaluationAdmissibility.ADMISSIBLE,
                vintage=new_vintage,
            )
        write_result = await self._repository.add_evaluation_vintage(new_vintage)
        final_outcome = (
            outcome_label
            if write_result.inserted
            else StructuredForecastEvaluationOutcome.UNCHANGED
        )
        return StructuredForecastEvaluationRecordResult(
            evaluation_key=evaluation_key,
            outcome=final_outcome,
            admissibility=ForecastEvaluationAdmissibility.ADMISSIBLE,
            vintage=new_vintage,
        )
