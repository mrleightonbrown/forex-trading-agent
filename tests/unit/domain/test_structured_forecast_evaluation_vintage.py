"""FX-65 Section 11: tests for `StructuredForecastEvaluationVintage`."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.domain.evidence_authentication_review import EvidenceAuthenticationReview
from forex_agent.domain.forecast_evaluation_metric import ForecastEvaluationMetric
from forex_agent.domain.forecast_evaluation_result import ForecastEvaluationResult
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.structured_forecast_evaluation_vintage import (
    StructuredForecastEvaluationVintage,
)
from forex_agent.domain.timestamps import UtcTimestamp


def _ts() -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, tzinfo=UTC))


def _vintage(**overrides: object) -> StructuredForecastEvaluationVintage:
    defaults: dict[str, object] = {
        "evaluation_key": "EVAL:BOC-MPS-2024Q4:boc-rate-protocol",
        "revision_sequence": 0,
        "forecast_claim_key": "BOC-MPS-2024Q4:CA_POLICY_RATE_LEVEL_AFTER_MEETING:AGGREGATE",
        "forecast_revision_sequence": 0,
        "protocol_key": "boc-rate-protocol",
        "protocol_version_sequence": 0,
        "outcome_definition_key": "BOC-RATE-OUTCOME",
        "outcome_definition_version_sequence": 0,
        "outcome_key": "BOC-RATE-DECISION-2024-12-11",
        "outcome_revision_sequence": 0,
        "evaluation_mode": ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        "algorithm_version": "fx65_v1",
        "availability": _ts(),
        "result": ForecastEvaluationResult(
            metric=ForecastEvaluationMetric.NUMERIC_ERROR,
            signed_error=Decimal("-0.50"),
            absolute_error=Decimal("0.50"),
            unit="PERCENT",
        ),
        "forecast_authentication_review": EvidenceAuthenticationReview(
            reviewed_by="FTA research operator", review_method="Direct review", reviewed_at=_ts()
        ),
    }
    defaults.update(overrides)
    return StructuredForecastEvaluationVintage(**defaults)  # type: ignore[arg-type]


def test_valid_evaluation_vintage() -> None:
    vintage = _vintage()
    assert vintage.result.signed_error == Decimal("-0.50")


def test_empty_evaluation_key_rejected() -> None:
    with pytest.raises(ValueError, match="evaluation_key"):
        _vintage(evaluation_key="")


def test_negative_revision_sequence_rejected() -> None:
    with pytest.raises(ValueError, match="revision_sequence"):
        _vintage(revision_sequence=-1)
