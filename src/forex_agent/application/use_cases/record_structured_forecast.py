"""FX-64: append-only recording of ONE structured-forecast vintage --
mirrors FX-62H's own CORRECTED determinism pattern exactly (the full
derived payload, not merely the numeric/categorical value, is part of
the historical-basis comparison), and FX-62's own atomic first-
registration pattern (`register_claim_with_first_vintage`).

**Capture eligibility is checked FIRST, unconditionally, before any
PIT/determinism logic runs** (Section 11) -- a non-`ELIGIBLE` verdict
returns a `REJECTED` result immediately, never reaching the
repository at all; nothing is ever persisted for a rejected candidate.

**Precedence, mirroring FX-56H.1/FX-59H/FX-62H's own corrected
lesson**: PIT ordering is checked BEFORE historical determinism. An
incoming vintage whose `availability` is earlier than the claim's own
latest recorded vintage (of EITHER provenance mode -- see `latest_
vintage_for_claim`'s own docstring) always raises `OutOfOrderStructured
ForecastError`, regardless of content.

**Determinism (Section 13), defined precisely**: for the SAME claim,
the SAME `algorithm_version`, and the SAME `evidence` object (the
WHOLE `ForecastEvidenceReference`, not merely its `evidence_kind` --
mirroring FX-62H's own corrected "evidence, not evidence_kind, is part
of the basis" lesson exactly), the derived forecast payload must be
IDENTICAL -- `(forecast_type, target_key, target_period, numeric_
value, unit, categorical_outcome, attribution)`. Checked across the
claim's ENTIRE stored vintage history (mirroring FX-59H/FX-62H's own
full-history rationale), not merely whichever vintage is currently
latest. A genuinely DIFFERENT evidence object (e.g. a source-issued
correction) is a different historical basis and is never compared
against this invariant -- it always mints a new, append-only revision
instead, exactly matching Section 13's own worked examples (v1(A) ->
v2(B) -> v1(A) succeeds; v1(A) -> v2(B) -> v1(C) is a determinism
error when C genuinely differs from A under the IDENTICAL basis)."""

from dataclasses import dataclass
from enum import Enum

from forex_agent.application.ports.structured_forecast_repository import (
    StructuredForecastRepository,
)
from forex_agent.application.use_cases.validate_structured_forecast_candidate import (
    StructuredForecastCandidate,
    ValidateStructuredForecastCandidate,
)
from forex_agent.domain.forecast_attribution import ForecastAttribution
from forex_agent.domain.forecast_capture_eligibility import ForecastCaptureEligibility
from forex_agent.domain.forecast_claim import ForecastClaim
from forex_agent.domain.forecast_evidence_reference import ForecastEvidenceReference
from forex_agent.domain.forecast_target_period import ForecastTargetPeriod
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.structured_forecast_vintage import StructuredForecastVintage
from forex_agent.domain.timestamps import UtcTimestamp

_Payload = tuple[
    ForecastType,
    str,
    ForecastTargetPeriod,
    object,
    object,
    object,
    ForecastAttribution,
]


def _payload_of(vintage: StructuredForecastVintage) -> _Payload:
    return (
        vintage.forecast_type,
        vintage.target_key,
        vintage.target_period,
        vintage.numeric_value,
        vintage.unit,
        vintage.categorical_outcome,
        vintage.attribution,
    )


class StructuredForecastOutcome(Enum):
    CREATED = "CREATED"
    REVISION_ADDED = "REVISION_ADDED"
    UNCHANGED = "UNCHANGED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class StructuredForecastRecordResult:
    claim_key: str
    outcome: StructuredForecastOutcome
    eligibility: ForecastCaptureEligibility
    reason: str | None = None
    vintage: StructuredForecastVintage | None = None
    """`None` only when `outcome is REJECTED`."""


class OutOfOrderStructuredForecastError(Exception):
    """Raised when an incoming vintage claims an `availability`
    earlier than the claim's own latest recorded vintage (of EITHER
    provenance mode)."""

    def __init__(
        self,
        claim_key: str,
        latest_availability: UtcTimestamp,
        incoming_availability: UtcTimestamp,
    ) -> None:
        self.claim_key = claim_key
        self.latest_availability = latest_availability
        self.incoming_availability = incoming_availability
        super().__init__(
            f"structured forecast for claim_key={claim_key!r} claims availability="
            f"{incoming_availability.value.isoformat()}, earlier than the latest recorded "
            f"vintage's own availability={latest_availability.value.isoformat()} -- refusing "
            "to append a backdated assertion"
        )


class StructuredForecastDeterminismError(Exception):
    """Raised when the SAME `(claim_key, algorithm_version, evidence)`
    historical basis produces a DIFFERENT derived forecast payload
    than SOME ALREADY-STORED vintage for that exact basis."""

    def __init__(
        self,
        claim_key: str,
        algorithm_version: str,
        evidence: ForecastEvidenceReference,
        existing_payload: _Payload,
        incoming_payload: _Payload,
    ) -> None:
        self.claim_key = claim_key
        self.algorithm_version = algorithm_version
        self.evidence = evidence
        self.existing_payload = existing_payload
        self.incoming_payload = incoming_payload
        super().__init__(
            f"claim_key={claim_key!r}, algorithm_version={algorithm_version!r}, evidence="
            f"{evidence!r} already produced a DIFFERENT forecast payload: existing="
            f"{existing_payload!r}, incoming={incoming_payload!r} -- the SAME evidence read "
            "under the SAME policy version must never produce two different forecasts"
        )


class RecordStructuredForecast:
    """See the module docstring."""

    def __init__(
        self,
        repository: StructuredForecastRepository,
        validate: ValidateStructuredForecastCandidate | None = None,
    ) -> None:
        self._repository = repository
        self._validate = validate or ValidateStructuredForecastCandidate()

    async def __call__(
        self,
        candidate: StructuredForecastCandidate,
        *,
        registered_at: UtcTimestamp,
        correction_reason: str | None = None,
        dry_run: bool = False,
    ) -> StructuredForecastRecordResult:
        """`registered_at` is used ONLY when `claim_key` has never
        been registered before -- the durable `ForecastClaim.
        registered_at`, never revised afterward (mirrors FX-62's own
        `RecordSourceIdentityVintage` convention exactly). `dry_run=
        True` computes and returns the EXACT SAME outcome a real call
        would, using the EXACT SAME decision logic below, but never
        writes."""
        validation = self._validate(candidate)
        if validation.eligibility is not ForecastCaptureEligibility.ELIGIBLE:
            return StructuredForecastRecordResult(
                claim_key=candidate.claim_key,
                outcome=StructuredForecastOutcome.REJECTED,
                eligibility=validation.eligibility,
                reason=validation.reason,
            )
        assert validation.target_period is not None
        assert validation.attribution is not None
        assert validation.evidence is not None

        existing_claim = await self._repository.get_claim(candidate.claim_key)
        latest = (
            await self._repository.latest_vintage_for_claim(candidate.claim_key)
            if existing_claim is not None
            else None
        )

        if latest is not None and candidate.availability.value < latest.availability.value:
            raise OutOfOrderStructuredForecastError(
                candidate.claim_key, latest.availability, candidate.availability
            )

        incoming_payload = (
            candidate.forecast_type,
            candidate.target_key,
            validation.target_period,
            candidate.numeric_value,
            candidate.unit,
            candidate.categorical_outcome,
            validation.attribution,
        )

        if existing_claim is not None:
            history = await self._repository.list_vintages_for_claim(candidate.claim_key)
            for historical in history:
                if (
                    historical.algorithm_version == candidate.algorithm_version
                    and historical.evidence == validation.evidence
                    and _payload_of(historical) != incoming_payload
                ):
                    raise StructuredForecastDeterminismError(
                        candidate.claim_key,
                        candidate.algorithm_version,
                        validation.evidence,
                        _payload_of(historical),
                        incoming_payload,
                    )

        if existing_claim is None:
            claim = ForecastClaim(claim_key=candidate.claim_key, registered_at=registered_at)
            created_vintage = StructuredForecastVintage(
                claim_key=candidate.claim_key,
                revision_sequence=0,
                availability=candidate.availability,
                algorithm_version=candidate.algorithm_version,
                forecast_type=candidate.forecast_type,
                target_key=candidate.target_key,
                target_period=validation.target_period,
                attribution=validation.attribution,
                provenance_mode=candidate.provenance_mode,
                evidence=validation.evidence,
                numeric_value=candidate.numeric_value,
                unit=candidate.unit,
                categorical_outcome=candidate.categorical_outcome,
                original_publication_at=candidate.original_publication_at,
                correction_reason=correction_reason,
            )
            if dry_run:
                return StructuredForecastRecordResult(
                    claim_key=candidate.claim_key,
                    outcome=StructuredForecastOutcome.CREATED,
                    eligibility=ForecastCaptureEligibility.ELIGIBLE,
                    vintage=created_vintage,
                )
            registration = await self._repository.register_claim_with_first_vintage(
                claim, created_vintage
            )
            outcome = (
                StructuredForecastOutcome.CREATED
                if registration.created
                else StructuredForecastOutcome.UNCHANGED
            )
            return StructuredForecastRecordResult(
                claim_key=candidate.claim_key,
                outcome=outcome,
                eligibility=ForecastCaptureEligibility.ELIGIBLE,
                vintage=created_vintage,
            )

        assert latest is not None  # an existing claim always has >=1 vintage (atomic creation)

        if (
            latest.algorithm_version == candidate.algorithm_version
            and latest.evidence == validation.evidence
            and _payload_of(latest) == incoming_payload
        ):
            return StructuredForecastRecordResult(
                claim_key=candidate.claim_key,
                outcome=StructuredForecastOutcome.UNCHANGED,
                eligibility=ForecastCaptureEligibility.ELIGIBLE,
                vintage=latest,
            )

        revised_vintage = StructuredForecastVintage(
            claim_key=candidate.claim_key,
            revision_sequence=latest.revision_sequence + 1,
            availability=candidate.availability,
            algorithm_version=candidate.algorithm_version,
            forecast_type=candidate.forecast_type,
            target_key=candidate.target_key,
            target_period=validation.target_period,
            attribution=validation.attribution,
            provenance_mode=candidate.provenance_mode,
            evidence=validation.evidence,
            numeric_value=candidate.numeric_value,
            unit=candidate.unit,
            categorical_outcome=candidate.categorical_outcome,
            original_publication_at=candidate.original_publication_at,
            correction_reason=correction_reason,
        )
        if dry_run:
            return StructuredForecastRecordResult(
                claim_key=candidate.claim_key,
                outcome=StructuredForecastOutcome.REVISION_ADDED,
                eligibility=ForecastCaptureEligibility.ELIGIBLE,
                vintage=revised_vintage,
            )
        write_result = await self._repository.add_vintage(revised_vintage)
        outcome = (
            StructuredForecastOutcome.REVISION_ADDED
            if write_result.inserted
            else StructuredForecastOutcome.UNCHANGED
        )
        return StructuredForecastRecordResult(
            claim_key=candidate.claim_key,
            outcome=outcome,
            eligibility=ForecastCaptureEligibility.ELIGIBLE,
            vintage=revised_vintage,
        )
