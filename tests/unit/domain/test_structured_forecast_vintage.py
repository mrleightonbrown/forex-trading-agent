"""FX-64 Section 12/13: tests for `StructuredForecastVintage` --
numeric/categorical shape enforcement, Decimal precision, and
immutability."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.domain.forecast_attribution import ForecastAttribution
from forex_agent.domain.forecast_attribution_kind import ForecastAttributionKind
from forex_agent.domain.forecast_evidence_kind import ForecastEvidenceKind
from forex_agent.domain.forecast_evidence_reference import ForecastEvidenceReference
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.forecast_target_period import ForecastTargetPeriod
from forex_agent.domain.forecast_target_period_kind import ForecastTargetPeriodKind
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.structured_forecast_vintage import StructuredForecastVintage
from forex_agent.domain.timestamps import UtcTimestamp


def _ts(year: int = 2026, month: int = 1, day: int = 1) -> UtcTimestamp:
    return UtcTimestamp(datetime(year, month, day, tzinfo=UTC))


def _evidence() -> ForecastEvidenceReference:
    return ForecastEvidenceReference(
        evidence_kind=ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
        description="test evidence",
        document_identifier="DOC-1",
    )


def _attribution() -> ForecastAttribution:
    return ForecastAttribution(
        kind=ForecastAttributionKind.AGGREGATE_SURVEY_CONSENSUS, publisher_source_key="ECB"
    )


def _period() -> ForecastTargetPeriod:
    return ForecastTargetPeriod(
        period_kind=ForecastTargetPeriodKind.CALENDAR_YEAR, calendar_year=2025
    )


def _numeric_vintage(**overrides: object) -> StructuredForecastVintage:
    defaults: dict[str, object] = {
        "claim_key": "CLAIM-1",
        "revision_sequence": 0,
        "availability": _ts(),
        "algorithm_version": "fx64_v1",
        "forecast_type": ForecastType.NUMERIC_POINT,
        "target_key": "EA_HICP_YOY_ANNUAL_AVERAGE",
        "target_period": _period(),
        "attribution": _attribution(),
        "provenance_mode": ForecastProvenanceMode.PRODUCTION_OBSERVED,
        "evidence": _evidence(),
        "numeric_value": Decimal("1.9"),
        "unit": "PERCENT_YOY",
    }
    defaults.update(overrides)
    return StructuredForecastVintage(**defaults)  # type: ignore[arg-type]


def test_numeric_point_valid() -> None:
    vintage = _numeric_vintage()
    assert vintage.numeric_value == Decimal("1.9")


def test_numeric_point_requires_decimal_not_float() -> None:
    with pytest.raises(TypeError, match="Decimal"):
        _numeric_vintage(numeric_value=1.9)


def test_numeric_point_requires_unit() -> None:
    with pytest.raises(ValueError, match="unit"):
        _numeric_vintage(unit=None)


def test_numeric_point_rejects_categorical_outcome() -> None:
    with pytest.raises(ValueError, match="categorical_outcome"):
        _numeric_vintage(categorical_outcome="HIKE")


def test_categorical_event_valid() -> None:
    vintage = _numeric_vintage(
        forecast_type=ForecastType.CATEGORICAL_EVENT,
        numeric_value=None,
        unit=None,
        categorical_outcome="HIKE",
        target_key="CA_POLICY_RATE_LEVEL_AFTER_MEETING",
        target_period=ForecastTargetPeriod(
            period_kind=ForecastTargetPeriodKind.POLICY_MEETING,
            policy_meeting_identifier="BOC-2026-03-15",
        ),
    )
    assert vintage.categorical_outcome == "HIKE"


def test_categorical_event_requires_categorical_outcome() -> None:
    with pytest.raises(ValueError, match="categorical_outcome"):
        _numeric_vintage(
            forecast_type=ForecastType.CATEGORICAL_EVENT, numeric_value=None, unit=None
        )


def test_categorical_event_rejects_numeric_value() -> None:
    with pytest.raises(ValueError, match="numeric_value"):
        _numeric_vintage(
            forecast_type=ForecastType.CATEGORICAL_EVENT,
            categorical_outcome="HOLD",
            unit=None,
        )


def test_categorical_event_rejects_unit() -> None:
    with pytest.raises(ValueError, match="unit"):
        _numeric_vintage(
            forecast_type=ForecastType.CATEGORICAL_EVENT,
            categorical_outcome="HOLD",
            numeric_value=None,
        )


def test_empty_algorithm_version_rejected() -> None:
    with pytest.raises(ValueError, match="algorithm_version"):
        _numeric_vintage(algorithm_version="")


def test_wrong_target_period_type_rejected() -> None:
    with pytest.raises(TypeError, match="target_period"):
        _numeric_vintage(target_period="2025")


def test_wrong_attribution_type_rejected() -> None:
    with pytest.raises(TypeError, match="attribution"):
        _numeric_vintage(attribution="ECB")


def test_wrong_evidence_type_rejected() -> None:
    with pytest.raises(TypeError, match="evidence"):
        _numeric_vintage(evidence="some evidence")


def test_wrong_provenance_mode_type_rejected() -> None:
    with pytest.raises(TypeError, match="provenance_mode"):
        _numeric_vintage(provenance_mode="PRODUCTION_OBSERVED")


def test_vintage_is_immutable() -> None:
    vintage = _numeric_vintage()
    with pytest.raises(FrozenInstanceError):
        vintage.numeric_value = Decimal("2.0")  # type: ignore[misc]


def test_correction_reason_informational_only() -> None:
    vintage = _numeric_vintage(revision_sequence=1, correction_reason="initial transcription error")
    assert vintage.correction_reason == "initial transcription error"


def test_empty_correction_reason_rejected() -> None:
    with pytest.raises(ValueError, match="correction_reason"):
        _numeric_vintage(correction_reason="")


def test_retrospective_research_provenance_mode_valid() -> None:
    vintage = _numeric_vintage(
        provenance_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        original_publication_at=_ts(2023, 1, 20),
    )
    assert vintage.provenance_mode is ForecastProvenanceMode.RETROSPECTIVE_RESEARCH
    assert vintage.original_publication_at == _ts(2023, 1, 20)
