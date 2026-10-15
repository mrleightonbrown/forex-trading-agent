"""FX-66 Section 9/10/11: `CalculateForecastPerformance` -- computes
descriptive numeric/categorical metrics and a supported benchmark
comparison over an ALREADY-BUILT population. Deliberately pure (no
repository access, mirroring `AssessForecastPerformanceEvidence`):
every numeric/categorical value it needs is already attached to each
`ForecastPerformancePopulationMember` -- `evaluation.result` (FX-65's
own already-computed signed/absolute error or MATCH/MISMATCH) for the
headline metrics, and `forecast_vintage.categorical_outcome`/
`outcome_vintage.categorical_outcome`/`outcome_vintage.numeric_value`
only for the confusion matrix and naive-numeric-benchmark error (which
`ForecastEvaluationResult` does not itself carry).

**`Decimal` throughout** (CLAUDE.md), including RMSE's own square
root via `Decimal.sqrt()` -- never `float`.

**Missing values are EXCLUDED, never zero** (Section 9's own absolute
rule, `ForecastPerformanceMissingDataPolicy.EXCLUDE_FROM_DENOMINATOR`
-- the only policy value that exists): an empty accepted population
yields `numeric_summary=None`/`categorical_summary=None`, never a
degenerate zero.

**For `AUTHENTICATED_SERIES` only**, a second, already-built
`benchmark_population` must be supplied by the caller (this use case
performs no I/O of its own) -- pairing is by SHARED `outcome_key`
(FX-65H.2's own durable target-event identity), restricting BOTH the
source's own metric and the benchmark's own metric to EXACTLY the
paired subset (Section 11's own "do not compare different sample
windows" rule)."""

from decimal import Decimal

from forex_agent.application.use_cases.build_forecast_performance_population_as_of import (
    ForecastPerformancePopulation,
    ForecastPerformancePopulationMember,
)
from forex_agent.domain.forecast_performance_benchmark_comparison import (
    ForecastPerformanceBenchmarkComparison,
)
from forex_agent.domain.forecast_performance_benchmark_comparison_status import (
    ForecastPerformanceBenchmarkComparisonStatus,
)
from forex_agent.domain.forecast_performance_benchmark_definition import (
    ForecastPerformanceBenchmarkDefinition,
)
from forex_agent.domain.forecast_performance_benchmark_kind import (
    ForecastPerformanceBenchmarkKind,
)
from forex_agent.domain.forecast_performance_categorical_summary import (
    ForecastPerformanceCategoricalSummary,
)
from forex_agent.domain.forecast_performance_numeric_summary import (
    ForecastPerformanceNumericSummary,
)
from forex_agent.domain.forecast_type import ForecastType


def _mean(values: list[Decimal]) -> Decimal:
    return sum(values, Decimal(0)) / len(values)


def _numeric_summary(
    members: tuple[ForecastPerformancePopulationMember, ...],
) -> ForecastPerformanceNumericSummary | None:
    if not members:
        return None
    signed_errors: list[Decimal] = []
    absolute_errors: list[Decimal] = []
    units: set[str] = set()
    for m in members:
        result = m.evaluation.result
        assert result.signed_error is not None
        assert result.absolute_error is not None
        assert result.unit is not None
        signed_errors.append(result.signed_error)
        absolute_errors.append(result.absolute_error)
        units.add(result.unit)
    assert len(units) == 1

    mean_signed_error = _mean(signed_errors)
    mean_absolute_error = _mean(absolute_errors)
    mean_squared_error = _mean([e * e for e in signed_errors])
    return ForecastPerformanceNumericSummary(
        n=len(members),
        unit=next(iter(units)),
        mean_absolute_error=mean_absolute_error,
        mean_signed_error=mean_signed_error,
        root_mean_squared_error=mean_squared_error.sqrt(),
    )


def _categorical_summary(
    members: tuple[ForecastPerformancePopulationMember, ...],
) -> ForecastPerformanceCategoricalSummary | None:
    if not members:
        return None
    n = len(members)
    match_count = sum(
        1
        for m in members
        if m.evaluation.result.categorical_result is not None
        and m.evaluation.result.categorical_result.value == "MATCH"
    )
    mismatch_count = n - match_count

    confusion: dict[tuple[str, str], int] = {}
    realized: dict[str, int] = {}
    for m in members:
        predicted = m.forecast_vintage.categorical_outcome
        observed = m.outcome_vintage.categorical_outcome
        assert predicted is not None
        assert observed is not None
        confusion[(predicted, observed)] = confusion.get((predicted, observed), 0) + 1
        realized[observed] = realized.get(observed, 0) + 1

    return ForecastPerformanceCategoricalSummary(
        n=n,
        match_count=match_count,
        mismatch_count=mismatch_count,
        accuracy=Decimal(match_count) / Decimal(n),
        confusion_counts=tuple(sorted((p, o, c) for (p, o), c in confusion.items())),
        realized_class_distribution=tuple(sorted(realized.items())),
    )


def _naive_numeric_benchmark_errors(
    members: list[ForecastPerformancePopulationMember], reference_value: Decimal
) -> list[Decimal]:
    errors = []
    for m in members:
        observed = m.outcome_vintage.numeric_value
        assert observed is not None
        errors.append(abs(observed - reference_value))
    return errors


def _naive_categorical_benchmark_match_count(
    members: list[ForecastPerformancePopulationMember], predicted_class: str
) -> int:
    count = 0
    for m in members:
        observed = m.outcome_vintage.categorical_outcome
        assert observed is not None
        if observed == predicted_class:
            count += 1
    return count


def _numeric_comparison(
    benchmark: ForecastPerformanceBenchmarkDefinition,
    paired_count: int,
    source_mae: Decimal,
    benchmark_mae: Decimal,
) -> ForecastPerformanceBenchmarkComparison:
    return ForecastPerformanceBenchmarkComparison(
        status=ForecastPerformanceBenchmarkComparisonStatus.COMPARED,
        benchmark_key=benchmark.benchmark_key,
        benchmark_version_sequence=benchmark.version_sequence,
        paired_count=paired_count,
        source_mean_absolute_error=source_mae,
        benchmark_mean_absolute_error=benchmark_mae,
        mean_absolute_error_difference=source_mae - benchmark_mae,
        relative_mae_improvement=(
            Decimal(1) - (source_mae / benchmark_mae) if benchmark_mae > 0 else None
        ),
    )


def _categorical_comparison(
    benchmark: ForecastPerformanceBenchmarkDefinition,
    paired_count: int,
    source_accuracy: Decimal,
    benchmark_accuracy: Decimal,
) -> ForecastPerformanceBenchmarkComparison:
    return ForecastPerformanceBenchmarkComparison(
        status=ForecastPerformanceBenchmarkComparisonStatus.COMPARED,
        benchmark_key=benchmark.benchmark_key,
        benchmark_version_sequence=benchmark.version_sequence,
        paired_count=paired_count,
        source_accuracy=source_accuracy,
        benchmark_accuracy=benchmark_accuracy,
        accuracy_difference=source_accuracy - benchmark_accuracy,
    )


def _benchmark_comparison(
    population: ForecastPerformancePopulation,
    benchmark: ForecastPerformanceBenchmarkDefinition | None,
    benchmark_population: ForecastPerformancePopulation | None,
) -> ForecastPerformanceBenchmarkComparison:
    unavailable = ForecastPerformanceBenchmarkComparison(
        status=ForecastPerformanceBenchmarkComparisonStatus.BENCHMARK_UNAVAILABLE
    )
    if benchmark is None:
        return unavailable
    members = list(population.accepted)
    if not members:
        return unavailable

    if benchmark.kind is ForecastPerformanceBenchmarkKind.NAIVE_NUMERIC:
        assert benchmark.naive_numeric_reference_value is not None
        source_summary = _numeric_summary(tuple(members))
        assert source_summary is not None
        benchmark_mae = _mean(
            _naive_numeric_benchmark_errors(members, benchmark.naive_numeric_reference_value)
        )
        return _numeric_comparison(
            benchmark, len(members), source_summary.mean_absolute_error, benchmark_mae
        )

    if benchmark.kind is ForecastPerformanceBenchmarkKind.NAIVE_CATEGORICAL:
        assert benchmark.naive_categorical_class is not None
        source_cat_summary = _categorical_summary(tuple(members))
        assert source_cat_summary is not None
        benchmark_accuracy = Decimal(
            _naive_categorical_benchmark_match_count(members, benchmark.naive_categorical_class)
        ) / Decimal(len(members))
        return _categorical_comparison(
            benchmark, len(members), source_cat_summary.accuracy, benchmark_accuracy
        )

    assert benchmark.kind is ForecastPerformanceBenchmarkKind.AUTHENTICATED_SERIES
    if benchmark_population is None:
        return unavailable
    benchmark_by_outcome = {m.evaluation.outcome_key: m for m in benchmark_population.accepted}
    paired_source = [m for m in members if m.evaluation.outcome_key in benchmark_by_outcome]
    paired_benchmark = [benchmark_by_outcome[m.evaluation.outcome_key] for m in paired_source]
    if not paired_source:
        return unavailable

    if population.cohort.forecast_type is ForecastType.NUMERIC_POINT:
        numeric_source = _numeric_summary(tuple(paired_source))
        numeric_benchmark = _numeric_summary(tuple(paired_benchmark))
        assert numeric_source is not None
        assert numeric_benchmark is not None
        return _numeric_comparison(
            benchmark,
            len(paired_source),
            numeric_source.mean_absolute_error,
            numeric_benchmark.mean_absolute_error,
        )

    categorical_source = _categorical_summary(tuple(paired_source))
    categorical_benchmark = _categorical_summary(tuple(paired_benchmark))
    assert categorical_source is not None
    assert categorical_benchmark is not None
    return _categorical_comparison(
        benchmark, len(paired_source), categorical_source.accuracy, categorical_benchmark.accuracy
    )


class CalculateForecastPerformance:
    def __call__(
        self,
        population: ForecastPerformancePopulation,
        *,
        benchmark: ForecastPerformanceBenchmarkDefinition | None = None,
        benchmark_population: ForecastPerformancePopulation | None = None,
    ) -> tuple[
        ForecastPerformanceNumericSummary | None,
        ForecastPerformanceCategoricalSummary | None,
        ForecastPerformanceBenchmarkComparison,
    ]:
        if population.cohort.forecast_type is ForecastType.NUMERIC_POINT:
            numeric_summary = _numeric_summary(population.accepted)
            categorical_summary = None
        else:
            assert population.cohort.forecast_type is ForecastType.CATEGORICAL_EVENT
            numeric_summary = None
            categorical_summary = _categorical_summary(population.accepted)

        comparison = _benchmark_comparison(population, benchmark, benchmark_population)
        return numeric_summary, categorical_summary, comparison
