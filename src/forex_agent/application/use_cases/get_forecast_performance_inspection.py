"""FX-67 Section 5: `GetForecastPerformanceInspection` -- the
complete, read-only summary of ONE recorded performance snapshot.
Uses EXACT stored snapshot values throughout (numeric/categorical
metrics, diagnostics, benchmark comparison) -- never recomputes MAE,
accuracy, or any other metric independently (Section 5's own explicit
"do not recalculate... in the inspection layer" rule). A missing
benchmark, unavailable metric, or insufficient sample is represented
explicitly via the already-`None`/already-`BENCHMARK_UNAVAILABLE`
stored values -- never substituted with zero or inferred (Section
5's own "Missing values" rule).

Resolves the EXACT pinned cohort/methodology version (never "latest"
-- a cohort/methodology can itself be revised after a snapshot was
recorded, and this summary must describe what the snapshot was
ACTUALLY built from) and the cohort's own declared originator
identity, resolved as of the snapshot's own `knowledge_cutoff` (never
`now()`, mirroring `GetForecastEvaluationInspection`'s own PIT
discipline for the SAME reason: a later identity correction must
never silently change an earlier inspection's displayed name)."""

from dataclasses import dataclass

from forex_agent.application.ports.forecast_evaluation_repository import (
    ForecastEvaluationRepository,
)
from forex_agent.application.ports.forecast_performance_repository import (
    ForecastPerformanceRepository,
)
from forex_agent.application.ports.source_registry_repository import SourceRegistryRepository
from forex_agent.application.use_cases.forecast_performance_inspection_support import (
    ForecastPerformanceInspectionMode,
    find_exact_version,
    resolve_snapshot_for_inspection,
)
from forex_agent.application.use_cases.get_forecast_evaluation_inspection import (
    ResolvedOriginatorIdentity,
    resolve_originator_identity,
)
from forex_agent.application.use_cases.get_forecast_performance_limitations import (
    ForecastPerformanceLimitations,
    GetForecastPerformanceLimitations,
)
from forex_agent.domain.forecast_attribution import ForecastAttribution
from forex_agent.domain.forecast_evaluation_protocol import ForecastEvaluationProtocol
from forex_agent.domain.forecast_performance_cohort_definition import (
    ForecastPerformanceCohortDefinition,
)
from forex_agent.domain.forecast_performance_methodology import ForecastPerformanceMethodology
from forex_agent.domain.forecast_performance_snapshot import ForecastPerformanceSnapshot
from forex_agent.domain.forecast_target_definition import ForecastTargetDefinition
from forex_agent.domain.forecast_target_registry import target_by_key
from forex_agent.domain.timestamps import UtcTimestamp


class SnapshotNotVisibleForInspectionError(Exception):
    """No vintage of `snapshot_key` was visible, under `mode`, by
    `as_of`."""

    def __init__(self, snapshot_key: str) -> None:
        self.snapshot_key = snapshot_key
        super().__init__(f"snapshot_key={snapshot_key!r} is not visible for this mode/as_of")


@dataclass(frozen=True, slots=True)
class ForecastPerformanceInspection:
    snapshot: ForecastPerformanceSnapshot
    mode: ForecastPerformanceInspectionMode
    cohort: ForecastPerformanceCohortDefinition | None
    """`None` only on an integrity gap -- the pinned cohort version
    could no longer be resolved."""
    methodology: ForecastPerformanceMethodology | None
    """`None` only on an integrity gap -- see `cohort` above."""
    protocol: ForecastEvaluationProtocol | None
    """`None` whenever `cohort` itself is `None`, or the pinned
    protocol version could no longer be resolved."""
    target: ForecastTargetDefinition | None
    originator: ResolvedOriginatorIdentity | None
    """`None` only when `cohort` is `None` (there is then no
    originator to resolve)."""
    limitations: ForecastPerformanceLimitations


class GetForecastPerformanceInspection:
    def __init__(
        self,
        performance_repository: ForecastPerformanceRepository,
        evaluation_repository: ForecastEvaluationRepository,
        registry_repository: SourceRegistryRepository,
    ) -> None:
        self._performance_repository = performance_repository
        self._evaluation_repository = evaluation_repository
        self._registry_repository = registry_repository

    async def __call__(
        self,
        snapshot_key: str,
        mode: ForecastPerformanceInspectionMode,
        as_of: UtcTimestamp,
    ) -> ForecastPerformanceInspection:
        snapshot = await resolve_snapshot_for_inspection(
            self._performance_repository, snapshot_key, mode, as_of
        )
        if snapshot is None:
            raise SnapshotNotVisibleForInspectionError(snapshot_key)

        cohort_versions = await self._performance_repository.list_cohort_versions(
            snapshot.cohort_key
        )
        cohort = find_exact_version(cohort_versions, snapshot.cohort_version_sequence)

        methodology_versions = await self._performance_repository.list_methodology_versions(
            snapshot.methodology_key
        )
        methodology = find_exact_version(
            methodology_versions, snapshot.methodology_version_sequence
        )

        protocol: ForecastEvaluationProtocol | None = None
        target: ForecastTargetDefinition | None = None
        originator: ResolvedOriginatorIdentity | None = None
        if cohort is not None:
            protocol_versions = await self._evaluation_repository.list_protocol_versions(
                cohort.protocol_key
            )
            protocol = find_exact_version(protocol_versions, cohort.protocol_version_sequence)
            target = target_by_key(cohort.target_key)
            cohort_attribution = ForecastAttribution(
                kind=cohort.attribution_kind,
                publisher_source_key=cohort.originator_publisher_source_key,
                forecaster_source_key=cohort.originator_forecaster_source_key,
            )
            originator = await resolve_originator_identity(
                self._registry_repository, cohort_attribution, snapshot.knowledge_cutoff
            )

        limitations = GetForecastPerformanceLimitations()(
            snapshot.diagnostics,
            cohort.attribution_kind if cohort is not None else None,
            snapshot.benchmark_comparison,
            snapshot.evaluation_mode,
        )

        return ForecastPerformanceInspection(
            snapshot=snapshot,
            mode=mode,
            cohort=cohort,
            methodology=methodology,
            protocol=protocol,
            target=target,
            originator=originator,
            limitations=limitations,
        )
