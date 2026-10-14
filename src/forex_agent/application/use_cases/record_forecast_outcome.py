"""FX-65: append-only recording of ONE outcome vintage -- mirrors
FX-64's `RecordStructuredForecast` exactly, INCLUDING FX-64H's own
corrected provenance-consistency lesson from the start (Historical
correction handling is the architect's own explicit review priority
#4 for this story): a resubmission under the SAME `(definition_key,
definition_version_sequence, evidence)` basis must match EVERY field
material to historical interpretation -- both the substantive payload
AND `provenance_mode`/`provider_published_at` -- or it is rejected,
never silently absorbed or silently promoted/demoted.

**Precedence**: PIT ordering is checked first (cheap, universal, needs
no identity logic), THEN the outcome-identity-binding invariant
(H1/H2) -- for an EXISTING `outcome_key` (a revision), immutability is
verified via a plain read BEFORE historical determinism; for a
genuinely NEW `outcome_key`, the identity is claimed ATOMICALLY
together with its own first vintage, right where that vintage would
otherwise be written -- there is no separate "claim, then write" step
to race between for a first-ever registration. Historical determinism
itself is unchanged, mirroring FX-56H.1/FX-59H/FX-62H/FX-64's own
corrected lesson exactly.

**FX-65H.2's own outcome-identity-binding invariants (completing
FX-65H.1's own narrower version)**: (H1) no two DIFFERENT `outcome_
key`s may ever share the same measurement identity; (H2) one `outcome_
key` may never CHANGE the identity it first registered. BOTH are
enforced ATOMICALLY at the database layer (`claim_outcome_identity_
and_add_first_vintage`'s own two unique constraints on the binding
table, mirroring FX-62/64's own atomic first-registration pattern
exactly), not by a read-then-decide query -- see `docs/adr/0013...`'s
own FX-65H.2 addendum for why FX-65H.1's own version of this check
could not guarantee exclusivity under concurrent transactions, and
silently never checked H2 at all."""

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
from forex_agent.domain.forecast_outcome_identity import (
    NO_UNIT_SENTINEL,
    ForecastOutcomeIdentityBinding,
    canonical_target_period_key,
)
from forex_agent.domain.forecast_outcome_vintage import ForecastOutcomeVintage
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.forecast_target_period import ForecastTargetPeriod
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.timestamps import UtcTimestamp

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
    """FX-65H.2 (H1): raised when a candidate's own `outcome_key` is
    NOT the sole legitimate holder of its own measurement identity --
    some OTHER `outcome_key` already holds that exact identity.
    Prevents two different outcome identities from ever representing
    the SAME real-world outcome, which would otherwise let an
    evaluation caller obtain different results merely by choosing
    which one to evaluate against. Detected via the database's own
    atomic uniqueness constraint, never a read-then-decide query."""

    def __init__(
        self,
        outcome_key: str,
        attempted: ForecastOutcomeIdentityBinding,
        conflicting_outcome_key: str,
    ) -> None:
        self.outcome_key = outcome_key
        self.attempted = attempted
        self.conflicting_outcome_key = conflicting_outcome_key
        super().__init__(
            f"outcome_key={outcome_key!r} claims identity {attempted!r}, but "
            f"outcome_key={conflicting_outcome_key!r} already holds that EXACT identity -- "
            "refusing to let two different outcome identities represent the same real-world "
            "outcome"
        )


class ForecastOutcomeIdentityImmutabilityError(Exception):
    """FX-65H.2 (H2): raised when an ALREADY-BOUND `outcome_key`
    attempts to register a vintage under a DIFFERENT measurement
    identity than the one it first established -- a change to its own
    `definition_key`, `target_period`, `outcome_type`, or `unit`.
    Legitimate new revisions of the SAME observed variable/event
    (a corrected value, a new evidence basis) always share the
    IDENTICAL identity and are unaffected by this check."""

    def __init__(
        self,
        outcome_key: str,
        existing: ForecastOutcomeIdentityBinding,
        attempted: ForecastOutcomeIdentityBinding,
    ) -> None:
        self.outcome_key = outcome_key
        self.existing = existing
        self.attempted = attempted
        super().__init__(
            f"outcome_key={outcome_key!r} is durably bound to identity {existing!r}, but this "
            f"submission attempts identity {attempted!r} -- refusing to let an outcome_key "
            "change what it measures across its own revisions"
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

    async def _classify_identity(self, incoming: ForecastOutcomeIdentityBinding) -> None:
        """FX-65H.2 (H1/H2): PURELY read-only classification -- raises
        the correct exception for a genuine conflict, or returns
        normally when `incoming` is legitimate (a brand-new identity/
        key pair, or an exact resubmission of an already-bound
        identity). Used for `dry_run` simulation (which must never
        mutate) AND to classify WHY an atomic claim attempt failed."""
        existing_for_key = await self._repository.get_identity_binding_for_key(incoming.outcome_key)
        if existing_for_key is not None:
            if not existing_for_key.shares_identity_with(incoming):
                raise ForecastOutcomeIdentityImmutabilityError(
                    incoming.outcome_key, existing_for_key, incoming
                )
            return  # legitimate re-registration of an already-bound identity

        existing_for_identity = await self._repository.get_identity_binding_for_identity(
            incoming.definition_key,
            incoming.target_period_key,
            incoming.outcome_type,
            incoming.unit,
        )
        if (
            existing_for_identity is not None
            and existing_for_identity.outcome_key != incoming.outcome_key
        ):
            raise ForecastOutcomeIdentityConflictError(
                incoming.outcome_key, incoming, existing_for_identity.outcome_key
            )
        # Neither lookup found a conflict: a genuinely new claim.

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

        incoming_binding = ForecastOutcomeIdentityBinding(
            definition_key=candidate.definition_key,
            target_period_key=canonical_target_period_key(validation.target_period),
            outcome_type=candidate.outcome_type,
            unit=candidate.unit if candidate.unit is not None else NO_UNIT_SENTINEL,
            outcome_key=candidate.outcome_key,
        )

        latest = await self._repository.latest_outcome_vintage(candidate.outcome_key)
        if latest is not None and candidate.availability.value < latest.availability.value:
            raise OutOfOrderForecastOutcomeError(
                candidate.outcome_key, latest.availability, candidate.availability
            )

        if latest is not None:
            # An existing outcome_key's own identity is IMMUTABLE (H2)
            # -- the atomic claim-and-first-vintage path below is only
            # for a genuinely NEW outcome_key, so a revision's own
            # identity is verified here instead of re-claimed.
            existing_for_key = await self._repository.get_identity_binding_for_key(
                candidate.outcome_key
            )
            assert existing_for_key is not None  # a vintage exists, so a binding always does too
            if not existing_for_key.shares_identity_with(incoming_binding):
                raise ForecastOutcomeIdentityImmutabilityError(
                    candidate.outcome_key, existing_for_key, incoming_binding
                )
        elif dry_run:
            # A genuinely new outcome_key, simulated: read-only
            # classification only -- `dry_run` never mutates, so the
            # atomic claim-and-first-vintage path is never attempted.
            await self._classify_identity(incoming_binding)

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

        if latest is None:
            # FX-65H.2 (H1/H4): claim the identity AND write the first
            # vintage ATOMICALLY -- the ONLY place this invariant is
            # enforced for a brand-new outcome_key.
            claim_result = await self._repository.claim_outcome_identity_and_add_first_vintage(
                incoming_binding, new_vintage
            )
            if claim_result.claimed:
                return ForecastOutcomeRecordResult(
                    outcome_key=candidate.outcome_key,
                    outcome=ForecastOutcomeOutcome.CREATED,
                    eligibility=ForecastOutcomeCaptureEligibility.ELIGIBLE,
                    vintage=new_vintage,
                )
            # Lost the atomic claim -- classify authoritatively
            # (raises on a genuine H1/H2 conflict); falling through
            # means a concurrent, genuinely identical submission won
            # the race first, which is benign (mirrors FX-64's own
            # "lost the first-registration race" precedent exactly).
            await self._classify_identity(incoming_binding)
            return ForecastOutcomeRecordResult(
                outcome_key=candidate.outcome_key,
                outcome=ForecastOutcomeOutcome.UNCHANGED,
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
