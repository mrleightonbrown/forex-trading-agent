"""FX-65 Section 5/11: tests for `ValidateForecastOutcomeCandidate`."""

from datetime import UTC, datetime
from decimal import Decimal

from forex_agent.application.use_cases.validate_forecast_outcome_candidate import (
    ForecastOutcomeCandidate,
    ValidateForecastOutcomeCandidate,
)
from forex_agent.domain.forecast_evidence_kind import ForecastEvidenceKind
from forex_agent.domain.forecast_outcome_capture_eligibility import (
    ForecastOutcomeCaptureEligibility,
)
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.forecast_target_period_kind import ForecastTargetPeriodKind
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.timestamps import UtcTimestamp


def _ts() -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, tzinfo=UTC))


def _candidate(**overrides: object) -> ForecastOutcomeCandidate:
    defaults: dict[str, object] = {
        "outcome_key": "BOC-RATE-DECISION-2024-12-11",
        "availability": _ts(),
        "definition_key": "BOC-RATE-OUTCOME",
        "definition_version_sequence": 0,
        "target_period_kind": ForecastTargetPeriodKind.POLICY_MEETING,
        "policy_meeting_identifier": "BOC-2024-12-11",
        "outcome_type": ForecastType.NUMERIC_POINT,
        "evidence_kind": ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
        "evidence_description": "Official press release",
        "document_identifier": "BOC-PR-2024-12-11",
        "provenance_mode": ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        "reviewed_by": "FTA research operator",
        "review_method": "Direct review of official press release",
        "reviewed_at": _ts(),
        "numeric_value": Decimal("3.25"),
        "unit": "PERCENT",
    }
    defaults.update(overrides)
    return ForecastOutcomeCandidate(**defaults)  # type: ignore[arg-type]


def test_eligible_candidate() -> None:
    result = ValidateForecastOutcomeCandidate()(_candidate())
    assert result.eligibility is ForecastOutcomeCaptureEligibility.ELIGIBLE
    assert result.target_period is not None
    assert result.evidence is not None
    assert result.authentication_review is not None


def test_malformed_target_period_is_insufficient_specification() -> None:
    result = ValidateForecastOutcomeCandidate()(_candidate(policy_meeting_identifier=None))
    assert result.eligibility is ForecastOutcomeCaptureEligibility.INSUFFICIENT_SPECIFICATION


def test_missing_evidence_document_identifier_is_unverified_evidence() -> None:
    result = ValidateForecastOutcomeCandidate()(_candidate(document_identifier=None))
    assert result.eligibility is ForecastOutcomeCaptureEligibility.UNVERIFIED_EVIDENCE


def test_missing_reviewer_is_unverified_evidence() -> None:
    result = ValidateForecastOutcomeCandidate()(_candidate(reviewed_by=""))
    assert result.eligibility is ForecastOutcomeCaptureEligibility.UNVERIFIED_EVIDENCE


def test_numeric_without_unit_is_insufficient_specification() -> None:
    result = ValidateForecastOutcomeCandidate()(_candidate(unit=None))
    assert result.eligibility is ForecastOutcomeCaptureEligibility.INSUFFICIENT_SPECIFICATION
