from dataclasses import dataclass
from decimal import Decimal

from forex_agent.domain.forecast_performance_benchmark_comparison_status import (
    ForecastPerformanceBenchmarkComparisonStatus,
)


@dataclass(frozen=True, slots=True)
class ForecastPerformanceBenchmarkComparison:
    """FX-66 Section 11: a benchmark-relative DESCRIPTIVE comparison
    over EXACTLY the paired, shared-outcome-event population -- never
    a different sample window for the source versus the benchmark
    (Section 11's own explicit "do not compare different sample
    windows" rule). `relative_mae_improvement` is populated ONLY for
    `NUMERIC_ERROR` when `benchmark_mean_absolute_error` is strictly
    positive (division-by-zero and metric-shape guards, Section 11's
    own "only when... all observations are properly paired" rule).

    A `COMPARED` status never implies statistically demonstrated
    skill (Section 11's own closing warning) -- it is a paired
    descriptive figure, nothing more."""

    status: ForecastPerformanceBenchmarkComparisonStatus
    benchmark_key: str | None = None
    benchmark_version_sequence: int | None = None
    paired_count: int = 0
    source_mean_absolute_error: Decimal | None = None
    benchmark_mean_absolute_error: Decimal | None = None
    mean_absolute_error_difference: Decimal | None = None
    relative_mae_improvement: Decimal | None = None
    source_accuracy: Decimal | None = None
    benchmark_accuracy: Decimal | None = None
    accuracy_difference: Decimal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ForecastPerformanceBenchmarkComparisonStatus):
            raise TypeError(
                "status must be a ForecastPerformanceBenchmarkComparisonStatus, got "
                f"{type(self.status).__name__}"
            )
        if self.status is ForecastPerformanceBenchmarkComparisonStatus.BENCHMARK_UNAVAILABLE:
            if self.paired_count != 0:
                raise ValueError("paired_count must be 0 for BENCHMARK_UNAVAILABLE")
            for name in (
                "source_mean_absolute_error",
                "benchmark_mean_absolute_error",
                "mean_absolute_error_difference",
                "relative_mae_improvement",
                "source_accuracy",
                "benchmark_accuracy",
                "accuracy_difference",
            ):
                if getattr(self, name) is not None:
                    raise ValueError(f"{name} must be None for BENCHMARK_UNAVAILABLE")
        else:
            if self.benchmark_key is None or self.benchmark_version_sequence is None:
                raise ValueError(
                    "benchmark_key/benchmark_version_sequence are required for COMPARED"
                )
            if self.paired_count < 1:
                raise ValueError(
                    f"paired_count must be positive for COMPARED, got {self.paired_count}"
                )
            numeric_populated = self.source_mean_absolute_error is not None
            categorical_populated = self.source_accuracy is not None
            if numeric_populated == categorical_populated:
                raise ValueError(
                    "exactly one of the numeric or categorical comparison fields must be "
                    "populated for COMPARED"
                )
