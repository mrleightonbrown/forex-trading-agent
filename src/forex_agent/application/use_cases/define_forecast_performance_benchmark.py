"""FX-66 Section 11: append-only registration of ONE performance-
benchmark version -- mirrors `DefineForecastPerformanceCohort`'s own
pattern exactly."""

from dataclasses import dataclass
from enum import Enum

from forex_agent.application.ports.forecast_performance_repository import (
    ForecastPerformanceRepository,
)
from forex_agent.domain.forecast_performance_benchmark_definition import (
    ForecastPerformanceBenchmarkDefinition,
)

_ContentKey = tuple[object, ...]


def _content_of(benchmark: ForecastPerformanceBenchmarkDefinition) -> _ContentKey:
    return (
        benchmark.kind,
        benchmark.target_key,
        benchmark.horizon_category,
        benchmark.metric,
        benchmark.benchmark_cohort_key,
        benchmark.benchmark_cohort_version_sequence,
        benchmark.naive_categorical_class,
        benchmark.naive_numeric_reference_value,
        benchmark.naive_numeric_reference_description,
        benchmark.rationale,
    )


class ForecastPerformanceBenchmarkOutcome(Enum):
    CREATED = "CREATED"
    REVISION_ADDED = "REVISION_ADDED"
    UNCHANGED = "UNCHANGED"


@dataclass(frozen=True, slots=True)
class ForecastPerformanceBenchmarkRecordResult:
    benchmark_key: str
    outcome: ForecastPerformanceBenchmarkOutcome
    benchmark: ForecastPerformanceBenchmarkDefinition


class OutOfSequenceBenchmarkError(Exception):
    def __init__(self, benchmark_key: str, expected: int, got: int) -> None:
        self.benchmark_key = benchmark_key
        self.expected = expected
        self.got = got
        super().__init__(
            f"benchmark_key={benchmark_key!r} expected the next version_sequence={expected}, "
            f"got {got} -- versions must be registered strictly sequentially"
        )


class ForecastPerformanceBenchmarkConflictError(Exception):
    def __init__(
        self,
        benchmark_key: str,
        version_sequence: int,
        existing: ForecastPerformanceBenchmarkDefinition,
        incoming: ForecastPerformanceBenchmarkDefinition,
    ) -> None:
        self.benchmark_key = benchmark_key
        self.version_sequence = version_sequence
        self.existing = existing
        self.incoming = incoming
        super().__init__(
            f"benchmark_key={benchmark_key!r}, version_sequence={version_sequence} already "
            f"exists with different content: existing={existing!r}, incoming={incoming!r}"
        )


class DefineForecastPerformanceBenchmark:
    def __init__(self, repository: ForecastPerformanceRepository) -> None:
        self._repository = repository

    async def __call__(
        self, benchmark: ForecastPerformanceBenchmarkDefinition, *, dry_run: bool = False
    ) -> ForecastPerformanceBenchmarkRecordResult:
        existing_versions = await self._repository.list_benchmark_versions(benchmark.benchmark_key)
        matching = next(
            (b for b in existing_versions if b.version_sequence == benchmark.version_sequence),
            None,
        )
        if matching is not None:
            if _content_of(matching) == _content_of(benchmark):
                return ForecastPerformanceBenchmarkRecordResult(
                    benchmark_key=benchmark.benchmark_key,
                    outcome=ForecastPerformanceBenchmarkOutcome.UNCHANGED,
                    benchmark=matching,
                )
            raise ForecastPerformanceBenchmarkConflictError(
                benchmark.benchmark_key, benchmark.version_sequence, matching, benchmark
            )

        expected_next = max((b.version_sequence for b in existing_versions), default=-1) + 1
        if benchmark.version_sequence != expected_next:
            raise OutOfSequenceBenchmarkError(
                benchmark.benchmark_key, expected_next, benchmark.version_sequence
            )

        outcome = (
            ForecastPerformanceBenchmarkOutcome.CREATED
            if benchmark.version_sequence == 0
            else ForecastPerformanceBenchmarkOutcome.REVISION_ADDED
        )
        if dry_run:
            return ForecastPerformanceBenchmarkRecordResult(
                benchmark_key=benchmark.benchmark_key, outcome=outcome, benchmark=benchmark
            )
        write_result = await self._repository.add_benchmark_version(benchmark)
        final_outcome = (
            outcome if write_result.inserted else ForecastPerformanceBenchmarkOutcome.UNCHANGED
        )
        return ForecastPerformanceBenchmarkRecordResult(
            benchmark_key=benchmark.benchmark_key, outcome=final_outcome, benchmark=benchmark
        )
