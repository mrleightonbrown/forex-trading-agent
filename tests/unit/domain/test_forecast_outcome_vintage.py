"""FX-65 Section 5: tests for `ForecastOutcomeVintage` -- mirrors
`StructuredForecastVintage`'s own payload-shape test coverage."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.domain.evidence_authentication_review import EvidenceAuthenticationReview
from forex_agent.domain.forecast_evidence_kind import ForecastEvidenceKind
from forex_agent.domain.forecast_evidence_reference import ForecastEvidenceReference
from forex_agent.domain.forecast_outcome_vintage import ForecastOutcomeVintage
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.forecast_target_period import ForecastTargetPeriod
from forex_agent.domain.forecast_target_period_kind import ForecastTargetPeriodKind
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.timestamps import UtcTimestamp


def _ts(day: int = 1) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, day, tzinfo=UTC))


def _evidence() -> ForecastEvidenceReference:
    return ForecastEvidenceReference(
        evidence_kind=ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
        description="Official release",
        document_identifier="DOC-1",
    )


def _review() -> EvidenceAuthenticationReview:
    return EvidenceAuthenticationReview(
        reviewed_by="FTA research operator", review_method="Direct review", reviewed_at=_ts()
    )


def _vintage(**overrides: object) -> ForecastOutcomeVintage:
    defaults: dict[str, object] = {
        "outcome_key": "BOC-RATE-DECISION-2024-12-11",
        "revision_sequence": 0,
        "definition_key": "BOC-RATE-OUTCOME",
        "definition_version_sequence": 0,
        "availability": _ts(),
        "target_period": ForecastTargetPeriod(
            period_kind=ForecastTargetPeriodKind.POLICY_MEETING,
            policy_meeting_identifier="BOC-2024-12-11",
        ),
        "outcome_type": ForecastType.NUMERIC_POINT,
        "evidence": _evidence(),
        "authentication_review": _review(),
        "provenance_mode": ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        "numeric_value": Decimal("3.25"),
        "unit": "PERCENT",
    }
    defaults.update(overrides)
    return ForecastOutcomeVintage(**defaults)  # type: ignore[arg-type]


def test_valid_numeric_vintage() -> None:
    vintage = _vintage()
    assert vintage.numeric_value == Decimal("3.25")


def test_numeric_without_unit_rejected() -> None:
    with pytest.raises(ValueError, match="unit"):
        _vintage(unit=None)


def test_numeric_with_categorical_outcome_rejected() -> None:
    with pytest.raises(ValueError, match="categorical_outcome"):
        _vintage(categorical_outcome="CUT")


def test_valid_categorical_vintage() -> None:
    vintage = _vintage(
        outcome_type=ForecastType.CATEGORICAL_EVENT,
        numeric_value=None,
        unit=None,
        categorical_outcome="CUT",
    )
    assert vintage.categorical_outcome == "CUT"


def test_missing_authentication_review_rejected() -> None:
    with pytest.raises(TypeError, match="authentication_review"):
        _vintage(authentication_review=None)
