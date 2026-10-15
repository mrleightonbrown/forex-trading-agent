from dataclasses import dataclass
from decimal import Decimal

from forex_agent.domain._guards import require_decimal, require_revision_sequence
from forex_agent.domain.forecast_evaluation_metric import ForecastEvaluationMetric
from forex_agent.domain.forecast_performance_benchmark_kind import (
    ForecastPerformanceBenchmarkKind,
)
from forex_agent.domain.forecast_target_registry import target_by_key
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class ForecastPerformanceBenchmarkDefinition:
    """FX-66 Section 11: ONE append-only version of an immutable
    benchmark specification -- `(benchmark_key, version_sequence)` is
    the row's own identity, mirroring `ForecastEvaluationProtocol`'s
    own append-only-version shape exactly. `kind` structurally
    determines which of the three kind-specific field groups below is
    populated (never more than one, never none) -- see `__post_init__`.

    Benchmarks are compared against a cohort's own population strictly
    by SHARED `outcome_key` (`AUTHENTICATED_SERIES`) or uniformly
    (`NAIVE_CATEGORICAL`/`NAIVE_NUMERIC`) -- never by date proximity,
    and never derived from an outcome that was not yet known at the
    time the ORIGINAL forecast was issued (Section 11's own "do not
    invent actual benchmark forecasts from later revised outcomes")."""

    benchmark_key: str
    version_sequence: int
    kind: ForecastPerformanceBenchmarkKind
    target_key: str
    horizon_category: str
    metric: ForecastEvaluationMetric
    availability: UtcTimestamp
    rationale: str
    benchmark_cohort_key: str | None = None
    benchmark_cohort_version_sequence: int | None = None
    naive_categorical_class: str | None = None
    naive_numeric_reference_value: Decimal | None = None
    naive_numeric_reference_description: str | None = None
    correction_reason: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("benchmark_key", self.benchmark_key),
            ("target_key", self.target_key),
            ("horizon_category", self.horizon_category),
            ("rationale", self.rationale),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string, got {value!r}")
        require_revision_sequence(self.version_sequence)
        if not isinstance(self.kind, ForecastPerformanceBenchmarkKind):
            raise TypeError(
                f"kind must be a ForecastPerformanceBenchmarkKind, got {type(self.kind).__name__}"
            )
        if not isinstance(self.metric, ForecastEvaluationMetric):
            raise TypeError(
                f"metric must be a ForecastEvaluationMetric, got {type(self.metric).__name__}"
            )
        if not isinstance(self.availability, UtcTimestamp):
            raise TypeError(
                f"availability must be a UtcTimestamp, got {type(self.availability).__name__}"
            )
        if self.correction_reason is not None and (
            not isinstance(self.correction_reason, str) or not self.correction_reason.strip()
        ):
            raise ValueError(
                f"correction_reason must be a non-empty string or None, got "
                f"{self.correction_reason!r}"
            )
        if target_by_key(self.target_key) is None:
            raise ValueError(
                f"target_key={self.target_key!r} is not in the admitted forecast target registry"
            )

        if self.kind is ForecastPerformanceBenchmarkKind.AUTHENTICATED_SERIES:
            if (
                not isinstance(self.benchmark_cohort_key, str)
                or not self.benchmark_cohort_key.strip()
            ):
                raise ValueError("benchmark_cohort_key is required for AUTHENTICATED_SERIES")
            require_revision_sequence(self.benchmark_cohort_version_sequence)
            self._require_none(
                "naive_categorical_class",
                "naive_numeric_reference_value",
                "naive_numeric_reference_description",
            )
        elif self.kind is ForecastPerformanceBenchmarkKind.NAIVE_CATEGORICAL:
            if (
                not isinstance(self.naive_categorical_class, str)
                or not self.naive_categorical_class.strip()
            ):
                raise ValueError("naive_categorical_class is required for NAIVE_CATEGORICAL")
            if self.metric is not ForecastEvaluationMetric.CATEGORICAL_MATCH:
                raise ValueError("metric must be CATEGORICAL_MATCH for NAIVE_CATEGORICAL")
            self._require_none(
                "benchmark_cohort_key",
                "benchmark_cohort_version_sequence",
                "naive_numeric_reference_value",
                "naive_numeric_reference_description",
            )
        else:
            assert self.kind is ForecastPerformanceBenchmarkKind.NAIVE_NUMERIC
            require_decimal("naive_numeric_reference_value", self.naive_numeric_reference_value)
            if (
                not isinstance(self.naive_numeric_reference_description, str)
                or not self.naive_numeric_reference_description.strip()
            ):
                raise ValueError(
                    "naive_numeric_reference_description is required for NAIVE_NUMERIC"
                )
            if self.metric is not ForecastEvaluationMetric.NUMERIC_ERROR:
                raise ValueError("metric must be NUMERIC_ERROR for NAIVE_NUMERIC")
            self._require_none(
                "benchmark_cohort_key",
                "benchmark_cohort_version_sequence",
                "naive_categorical_class",
            )

    def _require_none(self, *field_names: str) -> None:
        for name in field_names:
            if getattr(self, name) is not None:
                raise ValueError(
                    f"{name} must be None for kind={self.kind.value!r}, got {getattr(self, name)!r}"
                )
