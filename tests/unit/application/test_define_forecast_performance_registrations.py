"""FX-66: tests for `DefineForecastPerformanceCohort`/`DefineForecast
PerformanceMethodology`/`DefineForecastPerformanceBenchmark` -- mirrors
FX-65's own `RecordForecastOutcomeDefinition`/`RecordForecastEvaluation
Protocol` test coverage (sequential versioning, exact-repeat idempotency,
conflict detection)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.application.use_cases.define_forecast_performance_benchmark import (
    DefineForecastPerformanceBenchmark,
    ForecastPerformanceBenchmarkConflictError,
    ForecastPerformanceBenchmarkOutcome,
    OutOfSequenceBenchmarkError,
)
from forex_agent.application.use_cases.define_forecast_performance_cohort import (
    DefineForecastPerformanceCohort,
    ForecastPerformanceCohortConflictError,
    ForecastPerformanceCohortOutcome,
    OutOfSequenceCohortError,
)
from forex_agent.application.use_cases.define_forecast_performance_methodology import (
    DefineForecastPerformanceMethodology,
    ForecastPerformanceMethodologyConflictError,
    ForecastPerformanceMethodologyOutcome,
    OutOfSequenceMethodologyError,
)
from forex_agent.domain.forecast_attribution_kind import ForecastAttributionKind
from forex_agent.domain.forecast_evaluation_metric import ForecastEvaluationMetric
from forex_agent.domain.forecast_performance_benchmark_definition import (
    ForecastPerformanceBenchmarkDefinition,
)
from forex_agent.domain.forecast_performance_benchmark_kind import (
    ForecastPerformanceBenchmarkKind,
)
from forex_agent.domain.forecast_performance_cohort_definition import (
    ForecastPerformanceCohortDefinition,
)
from forex_agent.domain.forecast_performance_duplicate_selection_policy import (
    ForecastPerformanceDuplicateSelectionPolicy,
)
from forex_agent.domain.forecast_performance_methodology import ForecastPerformanceMethodology
from forex_agent.domain.forecast_performance_missing_data_policy import (
    ForecastPerformanceMissingDataPolicy,
)
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.timestamps import UtcTimestamp
from tests.fakes.forecast_performance_repository import FakeForecastPerformanceRepository


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


def _methodology(**overrides: object) -> ForecastPerformanceMethodology:
    defaults: dict[str, object] = {
        "methodology_key": "test-methodology",
        "version_sequence": 0,
        "cohort_key": "test-cohort",
        "cohort_version_sequence": 0,
        "missing_data_policy": ForecastPerformanceMissingDataPolicy.EXCLUDE_FROM_DENOMINATOR,
        "algorithm_version": "fx66_v1",
        "availability": _ts(9),
        "rationale": "test methodology",
    }
    defaults.update(overrides)
    return ForecastPerformanceMethodology(**defaults)  # type: ignore[arg-type]


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


async def test_cohort_first_registration_is_created() -> None:
    repo = FakeForecastPerformanceRepository()
    result = await DefineForecastPerformanceCohort(repo)(_cohort())
    assert result.outcome is ForecastPerformanceCohortOutcome.CREATED


async def test_cohort_exact_repeat_is_unchanged() -> None:
    repo = FakeForecastPerformanceRepository()
    define = DefineForecastPerformanceCohort(repo)
    await define(_cohort())
    result = await define(_cohort(availability=_ts(20)))
    assert result.outcome is ForecastPerformanceCohortOutcome.UNCHANGED


async def test_cohort_conflicting_same_version_raises() -> None:
    repo = FakeForecastPerformanceRepository()
    define = DefineForecastPerformanceCohort(repo)
    await define(_cohort())
    with pytest.raises(ForecastPerformanceCohortConflictError):
        await define(_cohort(horizon_category="DIFFERENT-HORIZON"))


async def test_cohort_out_of_sequence_version_raises() -> None:
    repo = FakeForecastPerformanceRepository()
    define = DefineForecastPerformanceCohort(repo)
    with pytest.raises(OutOfSequenceCohortError):
        await define(_cohort(version_sequence=1))


async def test_cohort_revision_added_for_new_version() -> None:
    repo = FakeForecastPerformanceRepository()
    define = DefineForecastPerformanceCohort(repo)
    await define(_cohort())
    result = await define(_cohort(version_sequence=1, rationale="updated rationale"))
    assert result.outcome is ForecastPerformanceCohortOutcome.REVISION_ADDED


async def test_methodology_first_registration_is_created() -> None:
    repo = FakeForecastPerformanceRepository()
    result = await DefineForecastPerformanceMethodology(repo)(_methodology())
    assert result.outcome is ForecastPerformanceMethodologyOutcome.CREATED


async def test_methodology_exact_repeat_is_unchanged() -> None:
    repo = FakeForecastPerformanceRepository()
    define = DefineForecastPerformanceMethodology(repo)
    await define(_methodology())
    result = await define(_methodology(availability=_ts(20)))
    assert result.outcome is ForecastPerformanceMethodologyOutcome.UNCHANGED


async def test_methodology_conflict_raises() -> None:
    repo = FakeForecastPerformanceRepository()
    define = DefineForecastPerformanceMethodology(repo)
    await define(_methodology())
    with pytest.raises(ForecastPerformanceMethodologyConflictError):
        await define(_methodology(algorithm_version="fx66_v2"))


async def test_methodology_out_of_sequence_raises() -> None:
    repo = FakeForecastPerformanceRepository()
    define = DefineForecastPerformanceMethodology(repo)
    with pytest.raises(OutOfSequenceMethodologyError):
        await define(_methodology(version_sequence=2))


async def test_benchmark_first_registration_is_created() -> None:
    repo = FakeForecastPerformanceRepository()
    result = await DefineForecastPerformanceBenchmark(repo)(_benchmark())
    assert result.outcome is ForecastPerformanceBenchmarkOutcome.CREATED


async def test_benchmark_exact_repeat_is_unchanged() -> None:
    repo = FakeForecastPerformanceRepository()
    define = DefineForecastPerformanceBenchmark(repo)
    await define(_benchmark())
    result = await define(_benchmark(availability=_ts(20)))
    assert result.outcome is ForecastPerformanceBenchmarkOutcome.UNCHANGED


async def test_benchmark_conflict_raises() -> None:
    repo = FakeForecastPerformanceRepository()
    define = DefineForecastPerformanceBenchmark(repo)
    await define(_benchmark())
    with pytest.raises(ForecastPerformanceBenchmarkConflictError):
        await define(_benchmark(naive_numeric_reference_value=Decimal("9.0")))


async def test_benchmark_out_of_sequence_raises() -> None:
    repo = FakeForecastPerformanceRepository()
    define = DefineForecastPerformanceBenchmark(repo)
    with pytest.raises(OutOfSequenceBenchmarkError):
        await define(_benchmark(version_sequence=3))
