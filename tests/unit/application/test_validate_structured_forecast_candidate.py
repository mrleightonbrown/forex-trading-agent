"""FX-64 Section 11: tests for `ValidateStructuredForecastCandidate` --
a pure, side-effect-free capture-eligibility check."""

from datetime import UTC, datetime
from decimal import Decimal

from forex_agent.application.use_cases.validate_structured_forecast_candidate import (
    StructuredForecastCandidate,
    ValidateStructuredForecastCandidate,
)
from forex_agent.domain.forecast_attribution_kind import ForecastAttributionKind
from forex_agent.domain.forecast_capture_eligibility import ForecastCaptureEligibility
from forex_agent.domain.forecast_evidence_kind import ForecastEvidenceKind
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.forecast_target_period_kind import ForecastTargetPeriodKind
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.timestamps import UtcTimestamp


def _ts(year: int = 2026) -> UtcTimestamp:
    return UtcTimestamp(datetime(year, 1, 1, tzinfo=UTC))


def _candidate(**overrides: object) -> StructuredForecastCandidate:
    defaults: dict[str, object] = {
        "claim_key": "ECB-SPF-2025Q1:EA_HICP_YOY_ANNUAL_AVERAGE:AGGREGATE",
        "availability": _ts(),
        "algorithm_version": "fx64_v1",
        "forecast_type": ForecastType.NUMERIC_POINT,
        "target_key": "EA_HICP_YOY_ANNUAL_AVERAGE",
        "target_period_kind": ForecastTargetPeriodKind.CALENDAR_YEAR,
        "calendar_year": 2025,
        "attribution_kind": ForecastAttributionKind.AGGREGATE_SURVEY_CONSENSUS,
        "publisher_source_key": "ECB",
        "evidence_kind": ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
        "evidence_description": "Read from published survey results table.",
        "document_identifier": "ECB-SPF-2025Q1",
        "provenance_mode": ForecastProvenanceMode.PRODUCTION_OBSERVED,
        "numeric_value": Decimal("1.9"),
        "unit": "PERCENT_YOY",
    }
    defaults.update(overrides)
    return StructuredForecastCandidate(**defaults)  # type: ignore[arg-type]


def test_eligible_candidate() -> None:
    result = ValidateStructuredForecastCandidate()(_candidate())
    assert result.eligibility is ForecastCaptureEligibility.ELIGIBLE
    assert result.target_period is not None
    assert result.attribution is not None
    assert result.evidence is not None


def test_unadmitted_target_key_is_insufficient_specification() -> None:
    result = ValidateStructuredForecastCandidate()(_candidate(target_key="NOT_A_REAL_TARGET"))
    assert result.eligibility is ForecastCaptureEligibility.INSUFFICIENT_SPECIFICATION


def test_mismatched_period_kind_is_insufficient_specification() -> None:
    """EA_HICP_YOY_ANNUAL_AVERAGE requires CALENDAR_YEAR, not
    CALENDAR_QUARTER."""
    result = ValidateStructuredForecastCandidate()(
        _candidate(
            target_period_kind=ForecastTargetPeriodKind.CALENDAR_QUARTER,
            calendar_year=2025,
            calendar_quarter=1,
        )
    )
    assert result.eligibility is ForecastCaptureEligibility.INSUFFICIENT_SPECIFICATION


def test_malformed_target_period_is_insufficient_specification() -> None:
    result = ValidateStructuredForecastCandidate()(_candidate(calendar_year=None))
    assert result.eligibility is ForecastCaptureEligibility.INSUFFICIENT_SPECIFICATION


def test_unsupported_forecast_type_for_target() -> None:
    """EA_HICP_YOY_ANNUAL_AVERAGE only supports NUMERIC_POINT."""
    result = ValidateStructuredForecastCandidate()(
        _candidate(forecast_type=ForecastType.CATEGORICAL_EVENT, categorical_outcome="HIKE")
    )
    assert result.eligibility is ForecastCaptureEligibility.UNSUPPORTED_FORECAST_TYPE


def test_categorical_target_rejects_numeric_forecast_type() -> None:
    result = ValidateStructuredForecastCandidate()(
        _candidate(
            target_key="CA_POLICY_RATE_DECISION_HIKE_HOLD_CUT",
            target_period_kind=ForecastTargetPeriodKind.POLICY_MEETING,
            calendar_year=None,
            policy_meeting_identifier="BOC-2026-03-15",
            forecast_type=ForecastType.NUMERIC_POINT,
        )
    )
    assert result.eligibility is ForecastCaptureEligibility.UNSUPPORTED_FORECAST_TYPE


def test_ambiguous_attribution_named_institution_without_forecaster() -> None:
    result = ValidateStructuredForecastCandidate()(
        _candidate(attribution_kind=ForecastAttributionKind.NAMED_INSTITUTION)
    )
    assert result.eligibility is ForecastCaptureEligibility.AMBIGUOUS_ATTRIBUTION


def test_ambiguous_attribution_aggregate_with_named_forecaster() -> None:
    result = ValidateStructuredForecastCandidate()(
        _candidate(
            attribution_kind=ForecastAttributionKind.AGGREGATE_SURVEY_CONSENSUS,
            forecaster_source_key="ECB",
        )
    )
    assert result.eligibility is ForecastCaptureEligibility.AMBIGUOUS_ATTRIBUTION


def test_unverified_evidence_missing_document_identifier() -> None:
    result = ValidateStructuredForecastCandidate()(_candidate(document_identifier=None))
    assert result.eligibility is ForecastCaptureEligibility.UNVERIFIED_EVIDENCE


def test_unverified_evidence_empty_description() -> None:
    result = ValidateStructuredForecastCandidate()(_candidate(evidence_description=""))
    assert result.eligibility is ForecastCaptureEligibility.UNVERIFIED_EVIDENCE


def test_news_item_vintage_basis_evidence_eligible() -> None:
    result = ValidateStructuredForecastCandidate()(
        _candidate(
            evidence_kind=ForecastEvidenceKind.NEWS_ITEM_VINTAGE_BASIS,
            document_identifier=None,
            news_item_key="ITEM-1",
            basis_revision_sequence=0,
        )
    )
    assert result.eligibility is ForecastCaptureEligibility.ELIGIBLE
    assert result.evidence is not None
    assert result.evidence.news_item_key == "ITEM-1"


def test_numeric_value_without_unit_is_insufficient_specification() -> None:
    result = ValidateStructuredForecastCandidate()(_candidate(unit=None))
    assert result.eligibility is ForecastCaptureEligibility.INSUFFICIENT_SPECIFICATION


def test_vague_directional_statement_has_no_eligible_path() -> None:
    """Section 4.1's own explicit example: "inflation will be lower
    next year" has no exact value -- without a numeric_value, the
    final shape-validation step rejects it as INSUFFICIENT_
    SPECIFICATION (there is no eligible path for a candidate with
    neither a numeric_value nor a categorical_outcome)."""
    result = ValidateStructuredForecastCandidate()(
        _candidate(numeric_value=None, unit=None, categorical_outcome=None)
    )
    assert result.eligibility is ForecastCaptureEligibility.INSUFFICIENT_SPECIFICATION
