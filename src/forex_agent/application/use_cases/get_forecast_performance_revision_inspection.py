"""FX-67 Section 13: `GetForecastPerformanceRevisionInspection` --
the administrative "what corrections or additional evaluations became
known after the historical performance cutoff" view, built entirely
on top of FX-66H.1's own `InspectForecastPerformancePendingRevisions`
(reused UNCHANGED, never re-implemented) plus the EXACT pinned cohort
version a snapshot was built from.

Deliberately separate from `GetForecastPerformanceInspection`: this
use case's own result is NEVER folded back into a snapshot summary,
and never influences which revision a historical inspection displays
(FX-66H.1's own "do not mix administrative future-knowledge
diagnostics into a persisted historical performance result" rule,
restated here one layer up -- administrative inspection is NOT a
historical PIT replay, Section 13's own closing line)."""

from dataclasses import dataclass

from forex_agent.application.ports.forecast_performance_repository import (
    ForecastPerformanceRepository,
)
from forex_agent.application.use_cases.forecast_performance_inspection_support import (
    ForecastPerformanceInspectionMode,
    find_exact_version,
    resolve_snapshot_for_inspection,
)
from forex_agent.application.use_cases.inspect_forecast_performance_pending_revisions import (
    ForecastPerformancePendingRevisionReport,
    InspectForecastPerformancePendingRevisions,
)
from forex_agent.domain.timestamps import UtcTimestamp


class SnapshotNotVisibleForInspectionError(Exception):
    def __init__(self, snapshot_key: str) -> None:
        self.snapshot_key = snapshot_key
        super().__init__(f"snapshot_key={snapshot_key!r} is not visible for this mode/as_of")


class SnapshotCohortUnresolvedError(Exception):
    """The snapshot's own pinned cohort version could not be resolved
    -- without it, `InspectForecastPerformancePendingRevisions` has
    no structural-eligibility rules to replay, so this raises rather
    than silently inventing or omitting a cohort."""

    def __init__(self, cohort_key: str, cohort_version_sequence: int) -> None:
        self.cohort_key = cohort_key
        self.cohort_version_sequence = cohort_version_sequence
        super().__init__(
            f"cohort {cohort_key!r} version {cohort_version_sequence} could not be resolved"
        )


@dataclass(frozen=True, slots=True)
class ForecastPerformanceRevisionInspection:
    snapshot_key: str
    snapshot_recording_availability: UtcTimestamp
    report: ForecastPerformancePendingRevisionReport


class GetForecastPerformanceRevisionInspection:
    def __init__(
        self,
        performance_repository: ForecastPerformanceRepository,
        pending_revisions: InspectForecastPerformancePendingRevisions,
    ) -> None:
        self._performance_repository = performance_repository
        self._pending_revisions = pending_revisions

    async def __call__(
        self,
        snapshot_key: str,
        mode: ForecastPerformanceInspectionMode,
        as_of: UtcTimestamp,
        *,
        administrative_as_of: UtcTimestamp,
    ) -> ForecastPerformanceRevisionInspection:
        snapshot = await resolve_snapshot_for_inspection(
            self._performance_repository, snapshot_key, mode, as_of
        )
        if snapshot is None:
            raise SnapshotNotVisibleForInspectionError(snapshot_key)

        cohort_versions = await self._performance_repository.list_cohort_versions(
            snapshot.cohort_key
        )
        cohort = find_exact_version(cohort_versions, snapshot.cohort_version_sequence)
        if cohort is None:
            raise SnapshotCohortUnresolvedError(
                snapshot.cohort_key, snapshot.cohort_version_sequence
            )

        report = await self._pending_revisions(
            cohort,
            historical_cutoff=snapshot.knowledge_cutoff,
            administrative_as_of=administrative_as_of,
        )
        return ForecastPerformanceRevisionInspection(
            snapshot_key=snapshot.snapshot_key,
            snapshot_recording_availability=snapshot.availability,
            report=report,
        )
