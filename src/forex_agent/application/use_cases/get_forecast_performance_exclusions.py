"""FX-67 Section 7/14: `GetForecastPerformanceExclusions` -- paginated,
deterministically-ordered view over ONE snapshot's own existing
exclusion records. Exposes exactly what FX-66 already persisted
(`(evaluation_key, reason)` pairs) -- invents nothing, and keeps
accepted membership and exclusions in two clearly separate call paths
(Section 7's own "show exclusions and accepted membership separately"
rule; see `GetForecastPerformanceMembers` for the accepted side).

`NOT_YET_AVAILABLE`/`MISSING_OR_UNRESOLVED_OUTCOME`/`INCOMPATIBLE_
HORIZON` are currently unreachable by construction in `fx66_v1`
(see each reason's own docstring on `ForecastPerformanceExclusionReason`)
-- this use case never fabricates an exclusion under one of those
reasons merely because none exists; an empty page for a snapshot with
zero exclusions is the correct, honest result."""

from dataclasses import dataclass

from forex_agent.application.ports.forecast_performance_repository import (
    ForecastPerformanceRepository,
)
from forex_agent.application.use_cases.forecast_performance_inspection_support import (
    ForecastPerformanceInspectionMode,
    require_valid_limit,
    resolve_snapshot_for_inspection,
)
from forex_agent.domain.forecast_performance_exclusion_reason import (
    ForecastPerformanceExclusionReason,
)
from forex_agent.domain.timestamps import UtcTimestamp


class SnapshotNotVisibleForInspectionError(Exception):
    def __init__(self, snapshot_key: str) -> None:
        self.snapshot_key = snapshot_key
        super().__init__(f"snapshot_key={snapshot_key!r} is not visible for this mode/as_of")


@dataclass(frozen=True, slots=True)
class ForecastPerformanceExclusionPage:
    snapshot_key: str
    snapshot_revision_sequence: int
    exclusions: tuple[tuple[str, ForecastPerformanceExclusionReason], ...]
    excluded_by_reason: tuple[tuple[ForecastPerformanceExclusionReason, int], ...]
    """The snapshot's OWN already-persisted summary count per reason
    (`diagnostics.excluded_by_reason`) -- never recomputed from the
    page, since a page may be partial."""
    next_cursor: str | None


class GetForecastPerformanceExclusions:
    def __init__(self, performance_repository: ForecastPerformanceRepository) -> None:
        self._performance_repository = performance_repository

    async def __call__(
        self,
        snapshot_key: str,
        mode: ForecastPerformanceInspectionMode,
        as_of: UtcTimestamp,
        *,
        limit: int,
        after_key: str | None = None,
    ) -> ForecastPerformanceExclusionPage:
        require_valid_limit(limit)
        snapshot = await resolve_snapshot_for_inspection(
            self._performance_repository, snapshot_key, mode, as_of
        )
        if snapshot is None:
            raise SnapshotNotVisibleForInspectionError(snapshot_key)

        ordered = sorted(snapshot.exclusions, key=lambda pair: pair[0])
        page = tuple(e for e in ordered if after_key is None or e[0] > after_key)[:limit]
        next_cursor = page[-1][0] if len(page) == limit else None
        return ForecastPerformanceExclusionPage(
            snapshot_key=snapshot.snapshot_key,
            snapshot_revision_sequence=snapshot.revision_sequence,
            exclusions=page,
            excluded_by_reason=snapshot.diagnostics.excluded_by_reason,
            next_cursor=next_cursor,
        )
