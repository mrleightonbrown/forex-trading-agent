"""FX-67 Section 10: `GetForecastPerformanceBenchmarkInspection` --
explains the benchmark a snapshot was compared against, using EXACTLY
the comparison FX-66 already computed and persisted (`snapshot.
benchmark_comparison`) -- never a second, independently-recomputed
comparison.

Where `BENCHMARK_UNAVAILABLE`, that result is returned as the
ordinary, prominent result (Section 10's own "display that result
prominently in the ordinary inspection narrative" rule) -- never
omitted, never treated as an error."""

from dataclasses import dataclass

from forex_agent.application.ports.forecast_performance_repository import (
    ForecastPerformanceRepository,
)
from forex_agent.application.use_cases.forecast_performance_inspection_support import (
    find_exact_version,
    resolve_snapshot_for_inspection,
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
from forex_agent.domain.forecast_performance_inspection_mode import (
    ForecastPerformanceInspectionMode,
)
from forex_agent.domain.forecast_target_definition import ForecastTargetDefinition
from forex_agent.domain.forecast_target_registry import target_by_key
from forex_agent.domain.timestamps import UtcTimestamp


class SnapshotNotVisibleForInspectionError(Exception):
    def __init__(self, snapshot_key: str) -> None:
        self.snapshot_key = snapshot_key
        super().__init__(f"snapshot_key={snapshot_key!r} is not visible for this mode/as_of")


@dataclass(frozen=True, slots=True)
class ForecastPerformanceBenchmarkInspection:
    comparison: ForecastPerformanceBenchmarkComparison
    benchmark: ForecastPerformanceBenchmarkDefinition | None
    """`None` whenever `comparison.status` is `BENCHMARK_UNAVAILABLE`,
    OR when `COMPARED` but the pinned benchmark version could not be
    resolved (an integrity gap, surfaced via `benchmark_unresolved`)."""
    benchmark_target: ForecastTargetDefinition | None
    benchmark_unresolved: bool
    """`True` only in the integrity-gap case described above --
    distinguishes "no benchmark was ever pinned" from "a benchmark was
    pinned but can no longer be resolved"."""
    is_complete_pairing: bool
    """`True` iff `COMPARED` and every accepted member paired against
    the benchmark; always `False` for `BENCHMARK_UNAVAILABLE`."""


class GetForecastPerformanceBenchmarkInspection:
    def __init__(self, performance_repository: ForecastPerformanceRepository) -> None:
        self._performance_repository = performance_repository

    async def __call__(
        self,
        snapshot_key: str,
        mode: ForecastPerformanceInspectionMode,
        as_of: UtcTimestamp,
    ) -> ForecastPerformanceBenchmarkInspection:
        snapshot = await resolve_snapshot_for_inspection(
            self._performance_repository, snapshot_key, mode, as_of
        )
        if snapshot is None:
            raise SnapshotNotVisibleForInspectionError(snapshot_key)

        comparison = snapshot.benchmark_comparison
        if comparison.status is ForecastPerformanceBenchmarkComparisonStatus.BENCHMARK_UNAVAILABLE:
            return ForecastPerformanceBenchmarkInspection(
                comparison=comparison,
                benchmark=None,
                benchmark_target=None,
                benchmark_unresolved=False,
                is_complete_pairing=False,
            )

        assert comparison.benchmark_key is not None
        assert comparison.benchmark_version_sequence is not None
        versions = await self._performance_repository.list_benchmark_versions(
            comparison.benchmark_key
        )
        benchmark = find_exact_version(versions, comparison.benchmark_version_sequence)
        benchmark_target = target_by_key(benchmark.target_key) if benchmark is not None else None
        accepted_count = len(snapshot.members)
        return ForecastPerformanceBenchmarkInspection(
            comparison=comparison,
            benchmark=benchmark,
            benchmark_target=benchmark_target,
            benchmark_unresolved=benchmark is None,
            is_complete_pairing=accepted_count > 0 and comparison.paired_count >= accepted_count,
        )
