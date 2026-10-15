"""FX-66: an in-memory fake implementing `ForecastPerformanceRepository`,
mirroring the real `SqlAlchemyForecastPerformanceRepository`'s own
exact latest-by-(availability, revision_sequence) selection and
idempotent-write semantics."""

from forex_agent.application.ports.forecast_performance_repository import (
    ForecastPerformanceBenchmarkWriteResult,
    ForecastPerformanceCohortWriteResult,
    ForecastPerformanceMethodologyWriteResult,
    ForecastPerformanceSnapshotWriteResult,
)
from forex_agent.domain.forecast_performance_benchmark_definition import (
    ForecastPerformanceBenchmarkDefinition,
)
from forex_agent.domain.forecast_performance_cohort_definition import (
    ForecastPerformanceCohortDefinition,
)
from forex_agent.domain.forecast_performance_methodology import ForecastPerformanceMethodology
from forex_agent.domain.forecast_performance_snapshot import ForecastPerformanceSnapshot
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.timestamps import UtcTimestamp


def _snapshot_sort_key(snapshot: ForecastPerformanceSnapshot) -> tuple[object, int]:
    return (snapshot.availability.value, snapshot.revision_sequence)


class FakeForecastPerformanceRepository:
    def __init__(self) -> None:
        self.cohorts: dict[str, list[ForecastPerformanceCohortDefinition]] = {}
        self.benchmarks: dict[str, list[ForecastPerformanceBenchmarkDefinition]] = {}
        self.methodologies: dict[str, list[ForecastPerformanceMethodology]] = {}
        self.snapshots: dict[str, list[ForecastPerformanceSnapshot]] = {}

    # --- cohorts ---

    async def latest_cohort_version(
        self, cohort_key: str
    ) -> ForecastPerformanceCohortDefinition | None:
        versions = self.cohorts.get(cohort_key, [])
        return max(versions, key=lambda c: c.version_sequence) if versions else None

    async def list_cohort_versions(
        self, cohort_key: str
    ) -> tuple[ForecastPerformanceCohortDefinition, ...]:
        return tuple(self.cohorts.get(cohort_key, ()))

    async def add_cohort_version(
        self, cohort: ForecastPerformanceCohortDefinition
    ) -> ForecastPerformanceCohortWriteResult:
        existing = self.cohorts.setdefault(cohort.cohort_key, [])
        if any(c.version_sequence == cohort.version_sequence for c in existing):
            return ForecastPerformanceCohortWriteResult(inserted=False)
        existing.append(cohort)
        return ForecastPerformanceCohortWriteResult(inserted=True)

    # --- benchmarks ---

    async def latest_benchmark_version(
        self, benchmark_key: str
    ) -> ForecastPerformanceBenchmarkDefinition | None:
        versions = self.benchmarks.get(benchmark_key, [])
        return max(versions, key=lambda b: b.version_sequence) if versions else None

    async def list_benchmark_versions(
        self, benchmark_key: str
    ) -> tuple[ForecastPerformanceBenchmarkDefinition, ...]:
        return tuple(self.benchmarks.get(benchmark_key, ()))

    async def add_benchmark_version(
        self, benchmark: ForecastPerformanceBenchmarkDefinition
    ) -> ForecastPerformanceBenchmarkWriteResult:
        existing = self.benchmarks.setdefault(benchmark.benchmark_key, [])
        if any(b.version_sequence == benchmark.version_sequence for b in existing):
            return ForecastPerformanceBenchmarkWriteResult(inserted=False)
        existing.append(benchmark)
        return ForecastPerformanceBenchmarkWriteResult(inserted=True)

    # --- methodologies ---

    async def latest_methodology_version(
        self, methodology_key: str
    ) -> ForecastPerformanceMethodology | None:
        versions = self.methodologies.get(methodology_key, [])
        return max(versions, key=lambda m: m.version_sequence) if versions else None

    async def list_methodology_versions(
        self, methodology_key: str
    ) -> tuple[ForecastPerformanceMethodology, ...]:
        return tuple(self.methodologies.get(methodology_key, ()))

    async def add_methodology_version(
        self, methodology: ForecastPerformanceMethodology
    ) -> ForecastPerformanceMethodologyWriteResult:
        existing = self.methodologies.setdefault(methodology.methodology_key, [])
        if any(m.version_sequence == methodology.version_sequence for m in existing):
            return ForecastPerformanceMethodologyWriteResult(inserted=False)
        existing.append(methodology)
        return ForecastPerformanceMethodologyWriteResult(inserted=True)

    # --- snapshots ---

    async def latest_snapshot_vintage(
        self, snapshot_key: str
    ) -> ForecastPerformanceSnapshot | None:
        vintages = self.snapshots.get(snapshot_key, ())
        return max(vintages, key=_snapshot_sort_key) if vintages else None

    async def list_vintages_for_snapshot(
        self, snapshot_key: str
    ) -> tuple[ForecastPerformanceSnapshot, ...]:
        return tuple(self.snapshots.get(snapshot_key, ()))

    async def add_snapshot_vintage(
        self, snapshot: ForecastPerformanceSnapshot
    ) -> ForecastPerformanceSnapshotWriteResult:
        existing = self.snapshots.setdefault(snapshot.snapshot_key, [])
        if any(s.revision_sequence == snapshot.revision_sequence for s in existing):
            return ForecastPerformanceSnapshotWriteResult(inserted=False)
        existing.append(snapshot)
        return ForecastPerformanceSnapshotWriteResult(inserted=True)

    async def latest_production_observed_snapshot_as_of(
        self, snapshot_key: str, as_of: UtcTimestamp
    ) -> ForecastPerformanceSnapshot | None:
        eligible = [
            s
            for s in self.snapshots.get(snapshot_key, ())
            if s.evaluation_mode is ForecastProvenanceMode.PRODUCTION_OBSERVED
            and s.availability.value <= as_of.value
        ]
        return max(eligible, key=_snapshot_sort_key) if eligible else None

    async def latest_snapshot_as_of_for_research(
        self, snapshot_key: str, research_as_of: UtcTimestamp
    ) -> ForecastPerformanceSnapshot | None:
        eligible = [
            s
            for s in self.snapshots.get(snapshot_key, ())
            if s.availability.value <= research_as_of.value
        ]
        return max(eligible, key=_snapshot_sort_key) if eligible else None
