"""FX-66: port for storing and PIT-querying FTA's own forecast-
performance cohorts, methodologies, benchmarks, and recorded
snapshots -- bundles all four concepts into ONE repository
(mirroring FX-65's own `ForecastOutcomeRepository`, which already
bundles two: outcome definitions + outcome vintages), since all four
exist only in service of ONE coherent responsibility: measuring
historical forecast performance. Mirrors every other FX-62/64/65
repository's own append-only-version (cohort/methodology/benchmark)
and append-only-vintage (snapshot) conventions, INCLUDING the
Section 13 production-versus-research read-path separation for
snapshots."""

from dataclasses import dataclass
from typing import Protocol

from forex_agent.domain.forecast_performance_benchmark_definition import (
    ForecastPerformanceBenchmarkDefinition,
)
from forex_agent.domain.forecast_performance_cohort_definition import (
    ForecastPerformanceCohortDefinition,
)
from forex_agent.domain.forecast_performance_methodology import ForecastPerformanceMethodology
from forex_agent.domain.forecast_performance_snapshot import ForecastPerformanceSnapshot
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class ForecastPerformanceCohortWriteResult:
    inserted: bool


@dataclass(frozen=True, slots=True)
class ForecastPerformanceMethodologyWriteResult:
    inserted: bool


@dataclass(frozen=True, slots=True)
class ForecastPerformanceBenchmarkWriteResult:
    inserted: bool


@dataclass(frozen=True, slots=True)
class ForecastPerformanceSnapshotWriteResult:
    inserted: bool


class ForecastPerformanceRepository(Protocol):
    async def latest_cohort_version(
        self, cohort_key: str
    ) -> ForecastPerformanceCohortDefinition | None: ...

    async def list_cohort_versions(
        self, cohort_key: str
    ) -> tuple[ForecastPerformanceCohortDefinition, ...]: ...

    async def add_cohort_version(
        self, cohort: ForecastPerformanceCohortDefinition
    ) -> ForecastPerformanceCohortWriteResult:
        """Append-only insert keyed on `(cohort_key, version_sequence)`
        -- `ON CONFLICT DO NOTHING` semantics."""
        ...

    async def latest_methodology_version(
        self, methodology_key: str
    ) -> ForecastPerformanceMethodology | None: ...

    async def list_methodology_versions(
        self, methodology_key: str
    ) -> tuple[ForecastPerformanceMethodology, ...]: ...

    async def add_methodology_version(
        self, methodology: ForecastPerformanceMethodology
    ) -> ForecastPerformanceMethodologyWriteResult:
        """Append-only insert keyed on `(methodology_key, version_
        sequence)`."""
        ...

    async def latest_benchmark_version(
        self, benchmark_key: str
    ) -> ForecastPerformanceBenchmarkDefinition | None: ...

    async def list_benchmark_versions(
        self, benchmark_key: str
    ) -> tuple[ForecastPerformanceBenchmarkDefinition, ...]: ...

    async def add_benchmark_version(
        self, benchmark: ForecastPerformanceBenchmarkDefinition
    ) -> ForecastPerformanceBenchmarkWriteResult:
        """Append-only insert keyed on `(benchmark_key, version_
        sequence)`."""
        ...

    async def latest_snapshot_vintage(
        self, snapshot_key: str
    ) -> ForecastPerformanceSnapshot | None:
        """The snapshot's own latest vintage by `(availability,
        revision_sequence)`, REGARDLESS of `evaluation_mode` -- an
        administrative read used only by `RecordForecastPerformance
        Snapshot`'s own PIT-ordering/idempotency checks."""
        ...

    async def list_vintages_for_snapshot(
        self, snapshot_key: str
    ) -> tuple[ForecastPerformanceSnapshot, ...]:
        """Every stored vintage of this snapshot -- used by the full-
        history determinism check."""
        ...

    async def add_snapshot_vintage(
        self, snapshot: ForecastPerformanceSnapshot
    ) -> ForecastPerformanceSnapshotWriteResult:
        """Append-only insert keyed on `(snapshot_key, revision_
        sequence)`."""
        ...

    async def latest_production_observed_snapshot_as_of(
        self, snapshot_key: str, as_of: UtcTimestamp
    ) -> ForecastPerformanceSnapshot | None:
        """The ONLY production PIT read this port offers. Returns the
        latest vintage with `evaluation_mode == PRODUCTION_OBSERVED`
        and `availability <= as_of` -- a `RETROSPECTIVE_RESEARCH`
        snapshot is NEVER returned here."""
        ...

    async def latest_snapshot_as_of_for_research(
        self, snapshot_key: str, research_as_of: UtcTimestamp
    ) -> ForecastPerformanceSnapshot | None:
        """The latest vintage with `availability <= research_as_of`,
        of EITHER evaluation mode -- deliberately named differently
        from the production method above."""
        ...

    async def list_distinct_snapshot_keys(
        self, *, cohort_key: str | None, limit: int, after_key: str | None
    ) -> tuple[str, ...]:
        """FX-67: the ONE new read method this story adds -- every
        OTHER snapshot read above requires an already-known `snapshot_
        key`, with no way to discover which keys exist at all. Returns
        up to `limit` DISTINCT `snapshot_key`s (across every vintage/
        revision), ordered lexicographically, optionally restricted to
        one `cohort_key`, strictly greater than `after_key` (the
        previous page's own last key -- a deterministic, unique cursor,
        never a nonunique timestamp). Read-only; never commits an
        unrelated pending write on a shared session."""
        ...
