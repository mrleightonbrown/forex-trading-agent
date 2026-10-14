"""FX-65 Section 7: tests for `ForecastEvaluationProtocol`."""

from datetime import UTC, datetime

import pytest

from forex_agent.domain.forecast_evaluation_metric import ForecastEvaluationMetric
from forex_agent.domain.forecast_evaluation_protocol import ForecastEvaluationProtocol
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.outcome_vintage_selection_policy import OutcomeVintageSelectionPolicy
from forex_agent.domain.timestamps import UtcTimestamp


def _ts() -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, tzinfo=UTC))


def _protocol(**overrides: object) -> ForecastEvaluationProtocol:
    defaults: dict[str, object] = {
        "protocol_key": "ECB-HICP-PROTOCOL",
        "version_sequence": 0,
        "supported_forecast_type": ForecastType.NUMERIC_POINT,
        "target_key": "EA_HICP_YOY_ANNUAL_AVERAGE",
        "outcome_definition_key": "ECB-HICP-OUTCOME",
        "outcome_definition_version_sequence": 0,
        "outcome_vintage_selection_policy": OutcomeVintageSelectionPolicy.FIRST_RELEASE,
        "metric": ForecastEvaluationMetric.NUMERIC_ERROR,
        "availability": _ts(),
        "rationale": "Compares SPF point forecast against first-released HICP outturn.",
    }
    defaults.update(overrides)
    return ForecastEvaluationProtocol(**defaults)  # type: ignore[arg-type]


def test_valid_numeric_protocol() -> None:
    protocol = _protocol()
    assert protocol.metric is ForecastEvaluationMetric.NUMERIC_ERROR


def test_metric_mismatch_rejected() -> None:
    with pytest.raises(ValueError, match="NUMERIC_ERROR"):
        _protocol(metric=ForecastEvaluationMetric.CATEGORICAL_MATCH)


def test_target_not_in_registry_rejected() -> None:
    with pytest.raises(ValueError, match="not in the admitted forecast target registry"):
        _protocol(target_key="NOT_A_REAL_TARGET")


def test_fixed_release_vintage_requires_pinned_revision() -> None:
    with pytest.raises(ValueError, match="fixed_outcome_revision_sequence is required"):
        _protocol(
            outcome_vintage_selection_policy=OutcomeVintageSelectionPolicy.FIXED_RELEASE_VINTAGE
        )


def test_fixed_revision_forbidden_outside_fixed_policy() -> None:
    with pytest.raises(ValueError, match="must be None unless"):
        _protocol(fixed_outcome_revision_sequence=2)


def test_categorical_protocol_requires_categorical_match_metric() -> None:
    protocol = _protocol(
        supported_forecast_type=ForecastType.CATEGORICAL_EVENT,
        target_key="CA_POLICY_RATE_DECISION_HIKE_HOLD_CUT",
        metric=ForecastEvaluationMetric.CATEGORICAL_MATCH,
    )
    assert protocol.supported_forecast_type is ForecastType.CATEGORICAL_EVENT
