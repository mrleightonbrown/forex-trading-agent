"""FX-67 Section 4/14: `ListForecastPerformanceSnapshots` -- the ONLY
way to DISCOVER which `snapshot_key`s exist at all (every other FX-66
read requires an already-known key). Thin wrapper over the one new
repository method this story adds (`list_distinct_snapshot_keys`),
bounded and deterministically ordered by `snapshot_key` ascending --
a unique cursor, never a nonunique timestamp (Section 14's own
explicit "avoid ordering solely by nonunique timestamps" rule)."""

from dataclasses import dataclass

from forex_agent.application.ports.forecast_performance_repository import (
    ForecastPerformanceRepository,
)
from forex_agent.application.use_cases.forecast_performance_inspection_support import (
    require_valid_limit,
)


@dataclass(frozen=True, slots=True)
class ForecastPerformanceSnapshotKeyPage:
    snapshot_keys: tuple[str, ...]
    next_cursor: str | None


class ListForecastPerformanceSnapshots:
    def __init__(self, performance_repository: ForecastPerformanceRepository) -> None:
        self._performance_repository = performance_repository

    async def __call__(
        self,
        *,
        cohort_key: str | None = None,
        limit: int,
        after_key: str | None = None,
    ) -> ForecastPerformanceSnapshotKeyPage:
        require_valid_limit(limit)
        keys = await self._performance_repository.list_distinct_snapshot_keys(
            cohort_key=cohort_key, limit=limit, after_key=after_key
        )
        next_cursor = keys[-1] if len(keys) == limit else None
        return ForecastPerformanceSnapshotKeyPage(snapshot_keys=keys, next_cursor=next_cursor)
