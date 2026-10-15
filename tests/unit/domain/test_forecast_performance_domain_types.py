"""FX-66: construction/validation tests for the new domain value
objects -- mirrors every other FX-62/64/65 domain test's own
"unconstructable to violate" coverage."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.domain.forecast_attribution_kind import ForecastAttributionKind
from forex_agent.domain.forecast_evaluation_metric import ForecastEvaluationMetric
from forex_agent.domain.forecast_performance_benchmark_definition import (
    ForecastPerformanceBenchmarkDefinition,
)
from forex_agent.domain.forecast_performance_benchmark_kind import (
    ForecastPerformanceBenchmarkKind,
)
from forex_agent.domain.forecast_performance_categorical_summary import (
    ForecastPerformanceCategoricalSummary,
)
from forex_agent.domain.forecast_performance_cohort_definition import (
    ForecastPerformanceCohortDefinition,
)
from forex_agent.domain.forecast_performance_duplicate_selection_policy import (
    ForecastPerformanceDuplicateSelectionPolicy,
)
from forex_agent.domain.forecast_performance_numeric_summary import (
    ForecastPerformanceNumericSummary,
)
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.timestamps import UtcTimestamp


def _ts(hour: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, hour, tzinfo=UTC))


def _cohort(**overrides: object) -> ForecastPerformanceCohortDefinition:
    defaults: dict[str, object] = {
        "cohort_key": "test-cohort",
        "version_sequence": 0,
        "attribution_kind": ForecastAttributionKind.AGGREGATE_SURVEY_CONSENSUS,
        "originator_publisher_source_key": "BANK_OF_CANADA",
        "target_key": "CA_POLICY_RATE_LEVEL_AFTER_MEETING",
        "forecast_type": ForecastType.NUMERIC_POINT,
        "horizon_category": "SAME-MEETING",
        "protocol_key": "test-protocol",
        "protocol_version_sequence": 0,
        "evaluation_mode": ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        "duplicate_selection_policy": (
            ForecastPerformanceDuplicateSelectionPolicy.EARLIEST_QUALIFYING_ISSUE
        ),
        "availability": _ts(9),
        "rationale": "test cohort",
    }
    defaults.update(overrides)
    return ForecastPerformanceCohortDefinition(**defaults)  # type: ignore[arg-type]


def test_cohort_rejects_mismatched_forecast_type() -> None:
    with pytest.raises(ValueError, match="forecast_type"):
        _cohort(forecast_type=ForecastType.CATEGORICAL_EVENT)


def test_cohort_named_institution_requires_forecaster_key() -> None:
    with pytest.raises(ValueError, match="originator_forecaster_source_key"):
        _cohort(attribution_kind=ForecastAttributionKind.NAMED_INSTITUTION)


def test_cohort_aggregate_forbids_forecaster_key() -> None:
    with pytest.raises(ValueError, match="originator_forecaster_source_key"):
        _cohort(originator_forecaster_source_key="SOME_FORECASTER")


def test_cohort_rejects_unknown_target_key() -> None:
    with pytest.raises(ValueError, match="target_key"):
        _cohort(target_key="__not_a_real_target__")


def test_cohort_rejects_inverted_issue_window() -> None:
    with pytest.raises(ValueError, match="issue_window"):
        _cohort(issue_window_start=_ts(20), issue_window_end=_ts(5))


def _benchmark(**overrides: object) -> ForecastPerformanceBenchmarkDefinition:
    defaults: dict[str, object] = {
        "benchmark_key": "test-benchmark",
        "version_sequence": 0,
        "kind": ForecastPerformanceBenchmarkKind.NAIVE_NUMERIC,
        "target_key": "CA_POLICY_RATE_LEVEL_AFTER_MEETING",
        "horizon_category": "SAME-MEETING",
        "metric": ForecastEvaluationMetric.NUMERIC_ERROR,
        "availability": _ts(9),
        "rationale": "test benchmark",
        "naive_numeric_reference_value": Decimal("3.5"),
        "naive_numeric_reference_description": "fixed reference",
    }
    defaults.update(overrides)
    return ForecastPerformanceBenchmarkDefinition(**defaults)  # type: ignore[arg-type]


def test_benchmark_naive_numeric_requires_reference_value() -> None:
    with pytest.raises(TypeError, match="naive_numeric_reference_value"):
        _benchmark(naive_numeric_reference_value=None, naive_numeric_reference_description=None)


def test_benchmark_naive_numeric_forbids_categorical_class() -> None:
    with pytest.raises(ValueError, match="naive_categorical_class"):
        _benchmark(naive_categorical_class="HOLD")


def test_benchmark_authenticated_series_requires_cohort_pin() -> None:
    with pytest.raises(ValueError, match="benchmark_cohort_key"):
        _benchmark(
            kind=ForecastPerformanceBenchmarkKind.AUTHENTICATED_SERIES,
            naive_numeric_reference_value=None,
            naive_numeric_reference_description=None,
        )


def test_benchmark_rejects_metric_mismatch() -> None:
    with pytest.raises(ValueError, match="metric"):
        _benchmark(metric=ForecastEvaluationMetric.CATEGORICAL_MATCH)


def test_numeric_summary_rejects_zero_n() -> None:
    with pytest.raises(ValueError, match="n"):
        ForecastPerformanceNumericSummary(
            n=0,
            unit="PERCENT",
            mean_absolute_error=Decimal("0"),
            mean_signed_error=Decimal("0"),
            root_mean_squared_error=Decimal("0"),
        )


def test_numeric_summary_rejects_negative_mae() -> None:
    with pytest.raises(ValueError, match="mean_absolute_error"):
        ForecastPerformanceNumericSummary(
            n=1,
            unit="PERCENT",
            mean_absolute_error=Decimal("-1"),
            mean_signed_error=Decimal("0"),
            root_mean_squared_error=Decimal("0"),
        )


def test_categorical_summary_rejects_inconsistent_counts() -> None:
    with pytest.raises(ValueError, match="match_count"):
        ForecastPerformanceCategoricalSummary(
            n=2,
            match_count=1,
            mismatch_count=0,
            accuracy=Decimal("0.5"),
            confusion_counts=(("HOLD", "HOLD", 1),),
            realized_class_distribution=(("HOLD", 1),),
        )


def test_categorical_summary_rejects_accuracy_out_of_range() -> None:
    with pytest.raises(ValueError, match="accuracy"):
        ForecastPerformanceCategoricalSummary(
            n=1,
            match_count=1,
            mismatch_count=0,
            accuracy=Decimal("1.5"),
            confusion_counts=(("HOLD", "HOLD", 1),),
            realized_class_distribution=(("HOLD", 1),),
        )
