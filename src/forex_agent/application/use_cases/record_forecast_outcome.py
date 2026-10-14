"""FX-65: append-only recording of ONE outcome vintage -- mirrors
FX-64's `RecordStructuredForecast` exactly, INCLUDING FX-64H's own
corrected provenance-consistency lesson from the start (Historical
correction handling is the architect's own explicit review priority
#4 for this story): a resubmission under the SAME `(definition_key,
definition_version_sequence, evidence)` basis must match EVERY field
material to historical interpretation -- both the substantive payload
AND `provenance_mode`/`provider_published_at` -- or it is rejected,
never silently absorbed or silently promoted/demoted.

**Precedence**: FX-65H.1's own outcome-identity-binding check (Section
2) is checked FIRST, even before PIT ordering -- a candidate whose own
`outcome_key` is not the sole legitimate identity for its own
`(definition_key, target_period, unit)` is a data-integrity defect,
more fundamental than any question of ordering or determinism against
that (illegitimate) identity's own history. PIT ordering is then
checked BEFORE historical determinism, mirroring FX-56H.1/FX-59H/
FX-62H/FX-64's own corrected lesson exactly.

**FX-65H.1's own outcome-identity-binding invariant**: no two
DIFFERENT `outcome_key`s may ever share the same `(definition_key,
target_period, unit)` identity. Without this, a caller evaluating a
forecast could obtain different results merely by choosing a
different, "compatible" `outcome_key` for what is really the SAME
real-world outcome -- exactly the substitution risk FX-65H.1 exists to
close. The FIRST `outcome_key` ever registered for a given identity
becomes its sole legitimate one; every later attempt to register a
DIFFERENT `outcome_key` for that same identity is refused."""

from dataclasses import dataclass
from enum import Enum

from forex_agent.application.ports.forecast_outcome_repository import ForecastOutcomeRepository
from forex_agent.application.use_cases.validate_forecast_outcome_candidate import (
    ForecastOutcomeCandidate,
    ValidateForecastOutcomeCandidate,
)
from forex_agent.domain.forecast_evidence_reference import ForecastEvidenceReference
from forex_agent.domain.forecast_outcome_capture_eligibility import (
    ForecastOutcomeCaptureEligibility,
)
from forex_agent.domain.forecast_outcome_vintage import ForecastOutcomeVintage
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.forecast_target_period import ForecastTargetPeriod
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.timestamps import UtcTimestamp

_Identity = tuple[str, ForecastTargetPeriod, ForecastType, str | None]


def _identity_of(vintage: ForecastOutcomeVintage) -> _Identity:
    return (vintage.definition_key, vintage.target_period, vintage.outcome_type, vintage.unit)


_Payload = tuple[ForecastType, ForecastTargetPeriod, object, object, object]
_Provenance = tuple[ForecastProvenanceMode, UtcTimestamp | None]


def _payload_of(vintage: ForecastOutcomeVintage) -> _Payload:
    return (
        vintage.outcome_type,
        vintage.target_period,
        vintage.numeric_value,
        vintage.unit,
        vintage.categorical_outcome,
    )


def _provenance_of(vintage: ForecastOutcomeVintage) -> _Provenance:
    return (vintage.provenance_mode, vintage.provider_published_at)


class ForecastOutcomeOutcome(Enum):
    CREATED = "CREATED"
    REVISION_ADDED = "REVISION_ADDED"
    UNCHANGED = "UNCHANGED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class ForecastOutcomeRecordResult:
    outcome_key: str
    outcome: ForecastOutcomeOutcome
    eligibility: ForecastOutcomeCaptureEligibility
    reason: str | None = None
    vintage: ForecastOutcomeVintage | None = None


class OutOfOrderForecastOutcomeError(Exception):
    def __init__(
        self,
        outcome_key: str,
        latest_availability: UtcTimestamp,
        incoming_availability: UtcTimestamp,
    ) -> None:
        self.outcome_key = outcome_key
        self.latest_availability = latest_availability
        self.incoming_availability = incoming_availability
        super().__init__(
            f"outcome for outcome_key={outcome_key!r} claims availability="
            f"{incoming_availability.value.isoformat()}, earlier than the latest recorded "
            f"vintage's own availability={latest_availability.value.isoformat()} -- refusing "
            "to append a backdated assertion"
        )


class ForecastOutcomeIdentityConflictError(Exception):
    """FX-65H.1 (Section 2): raised when a candidate's own `outcome_
    key` is NOT the sole legitimate identity for its own `(definition_
    key, target_period, unit)` -- some OTHER `outcome_key` already
    holds that exact identity. Prevents two different outcome
    identities from ever representing the SAME real-world outcome,
    which would otherwise let an evaluation caller obtain different
    results merely by choosing which one to evaluate against."""

    def __init__(
        self,
        outcome_key: str,
        identity: _Identity,
        conflicting_outcome_key: str,
    ) -> None:
        self.outcome_key = outcome_key
        self.identity = identity
        self.conflicting_outcome_key = conflicting_outcome_key
        super().__init__(
            f"outcome_key={outcome_key!r} claims identity "
            f"(definition_key, target_period, outcome_type, unit)={identity!r}, but "
            f"outcome_key={conflicting_outcome_key!r} already holds that EXACT identity -- "
            "refusing to let two different outcome identities represent the same real-world "
            "outcome"
        )


class ForecastOutcomeDeterminismError(Exception):
    def __init__(
        self,
        outcome_key: str,
        evidence: ForecastEvidenceReference,
        existing_payload: _Payload,
        incoming_payload: _Payload,
    ) -> None:
        self.outcome_key = outcome_key
        self.evidence = evidence
        self.existing_payload = existing_payload
        self.incoming_payload = incoming_payload
        super().__init__(
            f"outcome_key={outcome_key!r}, evidence={evidence!r} already produced a DIFFERENT "
            f"payload: existing={existing_payload!r}, incoming={incoming_payload!r}"
        )


class ForecastOutcomeProvenanceConsistencyError(Exception):
    """Mirrors FX-64H's own `StructuredForecastProvenanceConsistency
    Error` exactly: the SAME evidentiary basis producing the IDENTICAL
    payload must also agree on `provenance_mode`/`provider_published_
    at`, or this is raised and nothing is written. A genuine
    provenance correction requires genuinely NEW evidence."""

    def __init__(
        self,
        outcome_key: str,
        evidence: ForecastEvidenceReference,
        existing_provenance: _Provenance,
        incoming_provenance: _Provenance,
    ) -> None:
        self.outcome_key = outcome_key
        self.evidence = evidence
        self.existing_provenance = existing_provenance
        self.incoming_provenance = incoming_provenance
        super().__init__(
            f"outcome_key={outcome_key!r}, evidence={evidence!r} already recorded provenance="
            f"{existing_provenance!r}, but the incoming submission claims "
            f"{incoming_provenance!r} under the SAME evidentiary basis and identical payload"
        )


class RecordForecastOutcome:
    def __init__(
        self,
        repository: ForecastOutcomeRepository,
        validate: ValidateForecastOutcomeCandidate | None = None,
    ) -> None:
        self._repository = repository
        self._validate = validate or ValidateForecastOutcomeCandidate()

    async def __call__(
        self,
        candidate: ForecastOutcomeCandidate,
        *,
        correction_reason: str | None = None,
        dry_run: bool = False,
    ) -> ForecastOutcomeRecordResult:
        validation = self._validate(candidate)
        if validation.eligibility is not ForecastOutcomeCaptureEligibility.ELIGIBLE:
            return ForecastOutcomeRecordResult(
                outcome_key=candidate.outcome_key,
                outcome=ForecastOutcomeOutcome.REJECTED,
                eligibility=validation.eligibility,
                reason=validation.reason,
            )
        assert validation.target_period is not None
        assert validation.evidence is not None
        assert validation.authentication_review is not None

        incoming_identity: _Identity = (
            candidate.definition_key,
            validation.target_period,
            candidate.outcome_type,
            candidate.unit,
        )
        definition_vintages = await self._repository.list_outcome_vintages_for_definition(
            candidate.definition_key
        )
        for other in definition_vintages:
            if other.outcome_key == candidate.outcome_key:
                continue
            if _identity_of(other) == incoming_identity:
                raise ForecastOutcomeIdentityConflictError(
                    candidate.outcome_key, incoming_identity, other.outcome_key
                )

        latest = await self._repository.latest_outcome_vintage(candidate.outcome_key)
        if latest is not None and candidate.availability.value < latest.availability.value:
            raise OutOfOrderForecastOutcomeError(
                candidate.outcome_key, latest.availability, candidate.availability
            )

        incoming_payload: _Payload = (
            candidate.outcome_type,
            validation.target_period,
            candidate.numeric_value,
            candidate.unit,
            candidate.categorical_outcome,
        )
        incoming_provenance: _Provenance = (
            candidate.provenance_mode,
            candidate.provider_published_at,
        )

        history = await self._repository.list_vintages_for_outcome(candidate.outcome_key)
        for historical in history:
            if (
                historical.definition_key != candidate.definition_key
                or historical.definition_version_sequence != candidate.definition_version_sequence
                or historical.evidence != validation.evidence
            ):
                continue
            if _payload_of(historical) != incoming_payload:
                raise ForecastOutcomeDeterminismError(
                    candidate.outcome_key,
                    validation.evidence,
                    _payload_of(historical),
                    incoming_payload,
                )
            if _provenance_of(historical) != incoming_provenance:
                raise ForecastOutcomeProvenanceConsistencyError(
                    candidate.outcome_key,
                    validation.evidence,
                    _provenance_of(historical),
                    incoming_provenance,
                )

        if (
            latest is not None
            and latest.definition_key == candidate.definition_key
            and latest.definition_version_sequence == candidate.definition_version_sequence
            and latest.evidence == validation.evidence
            and _payload_of(latest) == incoming_payload
            and _provenance_of(latest) == incoming_provenance
        ):
            return ForecastOutcomeRecordResult(
                outcome_key=candidate.outcome_key,
                outcome=ForecastOutcomeOutcome.UNCHANGED,
                eligibility=ForecastOutcomeCaptureEligibility.ELIGIBLE,
                vintage=latest,
            )

        next_revision = 0 if latest is None else latest.revision_sequence + 1
        new_vintage = ForecastOutcomeVintage(
            outcome_key=candidate.outcome_key,
            revision_sequence=next_revision,
            definition_key=candidate.definition_key,
            definition_version_sequence=candidate.definition_version_sequence,
            availability=candidate.availability,
            target_period=validation.target_period,
            outcome_type=candidate.outcome_type,
            evidence=validation.evidence,
            authentication_review=validation.authentication_review,
            provenance_mode=candidate.provenance_mode,
            numeric_value=candidate.numeric_value,
            unit=candidate.unit,
            categorical_outcome=candidate.categorical_outcome,
            provider_release_identifier=candidate.provider_release_identifier,
            provider_published_at=candidate.provider_published_at,
            content_integrity_reference=candidate.content_integrity_reference,
            correction_reason=correction_reason,
        )
        outcome_label = (
            ForecastOutcomeOutcome.CREATED
            if latest is None
            else ForecastOutcomeOutcome.REVISION_ADDED
        )
        if dry_run:
            return ForecastOutcomeRecordResult(
                outcome_key=candidate.outcome_key,
                outcome=outcome_label,
                eligibility=ForecastOutcomeCaptureEligibility.ELIGIBLE,
                vintage=new_vintage,
            )
        write_result = await self._repository.add_outcome_vintage(new_vintage)
        final_outcome = outcome_label if write_result.inserted else ForecastOutcomeOutcome.UNCHANGED
        return ForecastOutcomeRecordResult(
            outcome_key=candidate.outcome_key,
            outcome=final_outcome,
            eligibility=ForecastOutcomeCaptureEligibility.ELIGIBLE,
            vintage=new_vintage,
        )
