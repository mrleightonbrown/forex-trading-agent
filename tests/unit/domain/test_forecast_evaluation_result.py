"""FX-65 Section 7: tests for `ForecastEvaluationResult`."""

from decimal import Decimal

import pytest

from forex_agent.domain.categorical_evaluation_result import CategoricalEvaluationResult
from forex_agent.domain.forecast_evaluation_metric import ForecastEvaluationMetric
from forex_agent.domain.forecast_evaluation_result import ForecastEvaluationResult


def test_valid_numeric_result() -> None:
    result = ForecastEvaluationResult(
        metric=ForecastEvaluationMetric.NUMERIC_ERROR,
        signed_error=Decimal("-0.50"),
        absolute_error=Decimal("0.50"),
        unit="PERCENT",
    )
    assert result.signed_error == Decimal("-0.50")


def test_absolute_error_must_equal_abs_signed_error() -> None:
    with pytest.raises(ValueError, match="absolute_error"):
        ForecastEvaluationResult(
            metric=ForecastEvaluationMetric.NUMERIC_ERROR,
            signed_error=Decimal("-0.50"),
            absolute_error=Decimal("0.60"),
            unit="PERCENT",
        )


def test_numeric_without_unit_rejected() -> None:
    with pytest.raises(ValueError, match="unit"):
        ForecastEvaluationResult(
            metric=ForecastEvaluationMetric.NUMERIC_ERROR,
            signed_error=Decimal("0"),
            absolute_error=Decimal("0"),
        )


def test_valid_categorical_result() -> None:
    result = ForecastEvaluationResult(
        metric=ForecastEvaluationMetric.CATEGORICAL_MATCH,
        categorical_result=CategoricalEvaluationResult.MISMATCH,
    )
    assert result.categorical_result is CategoricalEvaluationResult.MISMATCH


def test_categorical_with_numeric_fields_rejected() -> None:
    with pytest.raises(ValueError, match="signed_error"):
        ForecastEvaluationResult(
            metric=ForecastEvaluationMetric.CATEGORICAL_MATCH,
            categorical_result=CategoricalEvaluationResult.MATCH,
            signed_error=Decimal("0"),
        )
