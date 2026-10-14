"""FX-65 Section 5/11: `ValidateForecastOutcomeCandidate` -- a PURE,
side-effect-free capture-eligibility check for ONE raw outcome
candidate, mirroring FX-64's own `ValidateStructuredForecastCandidate`
exactly: `ForecastOutcomeCandidate` is the RAW, loosely-typed shape a
caller actually has in hand; building each strict value object IS the
eligibility check itself."""

from dataclasses import dataclass
from decimal import Decimal

from forex_agent.domain.evidence_authentication_review import EvidenceAuthenticationReview
from forex_agent.domain.forecast_evidence_kind import ForecastEvidenceKind
from forex_agent.domain.forecast_evidence_reference import ForecastEvidenceReference
from forex_agent.domain.forecast_outcome_capture_eligibility import (
    ForecastOutcomeCaptureEligibility,
)
from forex_agent.domain.forecast_outcome_vintage import ForecastOutcomeVintage
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.forecast_target_period import ForecastTargetPeriod
from forex_agent.domain.forecast_target_period_kind import ForecastTargetPeriodKind
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class ForecastOutcomeCandidate:
    outcome_key: str
    availability: UtcTimestamp
    definition_key: str
    definition_version_sequence: int
    target_period_kind: ForecastTargetPeriodKind
    outcome_type: ForecastType
    evidence_kind: ForecastEvidenceKind
    evidence_description: str
    provenance_mode: ForecastProvenanceMode
    reviewed_by: str
    review_method: str
    reviewed_at: UtcTimestamp
    calendar_year: int | None = None
    calendar_quarter: int | None = None
    calendar_month: int | None = None
    specific_date: UtcTimestamp | None = None
    policy_meeting_identifier: str | None = None
    news_item_key: str | None = None
    basis_revision_sequence: int | None = None
    document_identifier: str | None = None
    document_locator: str | None = None
    official_reference_url: str | None = None
    content_fingerprint: str | None = None
    publisher_declared_publication_at: UtcTimestamp | None = None
    corroboration_reference: str | None = None
    numeric_value: Decimal | None = None
    unit: str | None = None
    categorical_outcome: str | None = None
    provider_release_identifier: str | None = None
    provider_published_at: UtcTimestamp | None = None
    content_integrity_reference: str | None = None


@dataclass(frozen=True, slots=True)
class ForecastOutcomeValidationResult:
    eligibility: ForecastOutcomeCaptureEligibility
    reason: str | None = None
    target_period: ForecastTargetPeriod | None = None
    """Populated iff `eligibility is ELIGIBLE`."""
    evidence: ForecastEvidenceReference | None = None
    """Populated iff `eligibility is ELIGIBLE`."""
    authentication_review: EvidenceAuthenticationReview | None = None
    """Populated iff `eligibility is ELIGIBLE`."""


class ValidateForecastOutcomeCandidate:
    """See the module docstring."""

    def __call__(self, candidate: ForecastOutcomeCandidate) -> ForecastOutcomeValidationResult:
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
            return ForecastOutcomeValidationResult(
                ForecastOutcomeCaptureEligibility.INSUFFICIENT_SPECIFICATION, reason=str(exc)
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
            return ForecastOutcomeValidationResult(
                ForecastOutcomeCaptureEligibility.UNVERIFIED_EVIDENCE, reason=str(exc)
            )

        try:
            authentication_review = EvidenceAuthenticationReview(
                reviewed_by=candidate.reviewed_by,
                review_method=candidate.review_method,
                reviewed_at=candidate.reviewed_at,
                corroboration_reference=candidate.corroboration_reference,
            )
        except (TypeError, ValueError) as exc:
            return ForecastOutcomeValidationResult(
                ForecastOutcomeCaptureEligibility.UNVERIFIED_EVIDENCE, reason=str(exc)
            )

        try:
            ForecastOutcomeVintage(
                outcome_key=candidate.outcome_key,
                revision_sequence=0,
                definition_key=candidate.definition_key,
                definition_version_sequence=candidate.definition_version_sequence,
                availability=candidate.availability,
                target_period=target_period,
                outcome_type=candidate.outcome_type,
                evidence=evidence,
                authentication_review=authentication_review,
                provenance_mode=candidate.provenance_mode,
                numeric_value=candidate.numeric_value,
                unit=candidate.unit,
                categorical_outcome=candidate.categorical_outcome,
                provider_release_identifier=candidate.provider_release_identifier,
                provider_published_at=candidate.provider_published_at,
                content_integrity_reference=candidate.content_integrity_reference,
            )
        except (TypeError, ValueError) as exc:
            return ForecastOutcomeValidationResult(
                ForecastOutcomeCaptureEligibility.INSUFFICIENT_SPECIFICATION, reason=str(exc)
            )

        return ForecastOutcomeValidationResult(
            ForecastOutcomeCaptureEligibility.ELIGIBLE,
            target_period=target_period,
            evidence=evidence,
            authentication_review=authentication_review,
        )
