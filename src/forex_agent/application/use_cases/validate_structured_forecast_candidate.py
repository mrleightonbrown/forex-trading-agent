"""FX-64 Section 11: `ValidateStructuredForecastCandidate` -- a PURE,
side-effect-free capture-eligibility check. `StructuredForecastCandidate`
is deliberately the RAW shape a caller (an import script) actually has
in hand -- loosely-typed, pre-validation fields, mirroring FX-56's own
`NormalizedNewsObservation` DTO convention exactly -- so that building
each strict domain value object (`ForecastTargetPeriod`/`Forecast
Attribution`/`ForecastEvidenceReference`) IS itself the eligibility
check: a candidate whose own fields cannot assemble into a valid
object is classified into the matching rejection bucket (Section 11),
never allowed to crash the caller with an uncaught exception.

This is the ONLY place in FX-64 that performs this classification; both
`RecordStructuredForecast` and any future caller reuse this exact
function rather than re-implementing the same checks.

**FX-64H (H2) boundary, stated explicitly**: every check here,
including the `UNVERIFIED_EVIDENCE` branch, validates STRUCTURE --
whether the candidate's own raw fields can assemble into a well-formed
value object -- never whether a cited document is AUTHENTIC. `ELIGIBLE`
never implies, and must never be read by any caller as implying, that
the evidence was independently confirmed to exist or say what is
claimed. This function performs no fetch, hash check, or external
cross-reference, and this story deliberately adds none -- authenticating
a source is a human, out-of-band responsibility exercised BEFORE a
candidate is ever constructed (e.g. by whoever curates a pilot import's
own `evidence_description`/`document_identifier`, as documented in
that import script's own module docstring)."""

from dataclasses import dataclass
from decimal import Decimal

from forex_agent.domain.forecast_attribution import ForecastAttribution
from forex_agent.domain.forecast_attribution_kind import ForecastAttributionKind
from forex_agent.domain.forecast_capture_eligibility import ForecastCaptureEligibility
from forex_agent.domain.forecast_evidence_kind import ForecastEvidenceKind
from forex_agent.domain.forecast_evidence_reference import ForecastEvidenceReference
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.forecast_target_period import ForecastTargetPeriod
from forex_agent.domain.forecast_target_period_kind import ForecastTargetPeriodKind
from forex_agent.domain.forecast_target_registry import target_by_key
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.structured_forecast_vintage import StructuredForecastVintage
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class StructuredForecastCandidate:
    """See the module docstring. Every field here is a RAW value --
    none of `ForecastTargetPeriod`/`ForecastAttribution`/`Forecast
    EvidenceReference` is required to already exist; `Validate
    StructuredForecastCandidate` builds them."""

    claim_key: str
    availability: UtcTimestamp
    algorithm_version: str
    forecast_type: ForecastType
    target_key: str
    target_period_kind: ForecastTargetPeriodKind
    attribution_kind: ForecastAttributionKind
    publisher_source_key: str
    evidence_kind: ForecastEvidenceKind
    evidence_description: str
    provenance_mode: ForecastProvenanceMode
    calendar_year: int | None = None
    calendar_quarter: int | None = None
    calendar_month: int | None = None
    specific_date: UtcTimestamp | None = None
    policy_meeting_identifier: str | None = None
    forecaster_source_key: str | None = None
    anonymous_respondent_id: str | None = None
    news_item_key: str | None = None
    basis_revision_sequence: int | None = None
    document_identifier: str | None = None
    document_locator: str | None = None
    official_reference_url: str | None = None
    content_fingerprint: str | None = None
    publisher_declared_publication_at: UtcTimestamp | None = None
    numeric_value: Decimal | None = None
    unit: str | None = None
    categorical_outcome: str | None = None
    original_publication_at: UtcTimestamp | None = None


@dataclass(frozen=True, slots=True)
class StructuredForecastValidationResult:
    eligibility: ForecastCaptureEligibility
    reason: str | None = None
    target_period: ForecastTargetPeriod | None = None
    """Populated iff `eligibility is ELIGIBLE`."""
    attribution: ForecastAttribution | None = None
    """Populated iff `eligibility is ELIGIBLE`."""
    evidence: ForecastEvidenceReference | None = None
    """Populated iff `eligibility is ELIGIBLE`."""


class ValidateStructuredForecastCandidate:
    """See the module docstring."""

    def __call__(
        self, candidate: StructuredForecastCandidate
    ) -> StructuredForecastValidationResult:
        target_definition = target_by_key(candidate.target_key)
        if target_definition is None:
            return StructuredForecastValidationResult(
                ForecastCaptureEligibility.INSUFFICIENT_SPECIFICATION,
                reason=f"target_key={candidate.target_key!r} is not in the admitted registry",
            )
        if candidate.forecast_type not in target_definition.supported_forecast_types:
            return StructuredForecastValidationResult(
                ForecastCaptureEligibility.UNSUPPORTED_FORECAST_TYPE,
                reason=(
                    f"forecast_type={candidate.forecast_type.value!r} is not supported by "
                    f"target_key={candidate.target_key!r} (admits only "
                    f"{[t.value for t in target_definition.supported_forecast_types]!r})"
                ),
            )
        if candidate.target_period_kind is not target_definition.period_frequency:
            return StructuredForecastValidationResult(
                ForecastCaptureEligibility.INSUFFICIENT_SPECIFICATION,
                reason=(
                    f"target_period_kind={candidate.target_period_kind.value!r} does not match "
                    f"target_key={candidate.target_key!r}'s own admitted period_frequency="
                    f"{target_definition.period_frequency.value!r}"
                ),
            )

        try:
            target_period = ForecastTargetPeriod(
                period_kind=candidate.target_period_kind,
                calendar_year=candidate.calendar_year,
                calendar_quarter=candidate.calendar_quarter,
                calendar_month=candidate.calendar_month,
                specific_date=candidate.specific_date,
                policy_meeting_identifier=candidate.policy_meeting_identifier,
            )
        except (TypeError, ValueError) as exc:
            return StructuredForecastValidationResult(
                ForecastCaptureEligibility.INSUFFICIENT_SPECIFICATION, reason=str(exc)
            )

        try:
            attribution = ForecastAttribution(
                kind=candidate.attribution_kind,
                publisher_source_key=candidate.publisher_source_key,
                forecaster_source_key=candidate.forecaster_source_key,
                anonymous_respondent_id=candidate.anonymous_respondent_id,
            )
        except (TypeError, ValueError) as exc:
            return StructuredForecastValidationResult(
                ForecastCaptureEligibility.AMBIGUOUS_ATTRIBUTION, reason=str(exc)
            )

        try:
            evidence = ForecastEvidenceReference(
                evidence_kind=candidate.evidence_kind,
                description=candidate.evidence_description,
                news_item_key=candidate.news_item_key,
                basis_revision_sequence=candidate.basis_revision_sequence,
                document_identifier=candidate.document_identifier,
                document_locator=candidate.document_locator,
                official_reference_url=candidate.official_reference_url,
                content_fingerprint=candidate.content_fingerprint,
                publisher_declared_publication_at=candidate.publisher_declared_publication_at,
            )
        except (TypeError, ValueError) as exc:
            return StructuredForecastValidationResult(
                ForecastCaptureEligibility.UNVERIFIED_EVIDENCE, reason=str(exc)
            )

        try:
            StructuredForecastVintage(
                claim_key=candidate.claim_key,
                revision_sequence=0,
                availability=candidate.availability,
                algorithm_version=candidate.algorithm_version,
                forecast_type=candidate.forecast_type,
                target_key=candidate.target_key,
                target_period=target_period,
                attribution=attribution,
                provenance_mode=candidate.provenance_mode,
                evidence=evidence,
                numeric_value=candidate.numeric_value,
                unit=candidate.unit,
                categorical_outcome=candidate.categorical_outcome,
                original_publication_at=candidate.original_publication_at,
            )
        except (TypeError, ValueError) as exc:
            return StructuredForecastValidationResult(
                ForecastCaptureEligibility.INSUFFICIENT_SPECIFICATION, reason=str(exc)
            )

        return StructuredForecastValidationResult(
            ForecastCaptureEligibility.ELIGIBLE,
            target_period=target_period,
            attribution=attribution,
            evidence=evidence,
        )
