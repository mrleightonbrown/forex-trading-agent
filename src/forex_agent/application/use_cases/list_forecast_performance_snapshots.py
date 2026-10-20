"""FX-67 Section 4/14 + FX-67H (F67-01) correction: `ListForecastPerformance
Snapshots` -- the ONLY way to DISCOVER which `snapshot_key`s exist at
all (every other FX-66 read requires an already-known key). Bounded
and deterministically ordered by `snapshot_key` ascending -- a unique
cursor, never a nonunique timestamp (Section 14's own explicit "avoid
ordering solely by nonunique timestamps" rule).

**FX-67H correction**: `mode`/`as_of` are now REQUIRED keyword
arguments, with no default -- the original version discovered every
snapshot key unconditionally, honoring neither historical availability
nor the production/research mode boundary every OTHER FX-67 inspection
entry point already enforces (F67-01). There is no implicit "now" and
no implicit mode fallback here either, mirroring `ForecastPerformance
InspectionMode`'s own "unmissable at every call site" rule exactly."""

from dataclasses import dataclass

from forex_agent.application.ports.forecast_performance_repository import (
    ForecastPerformanceRepository,
)
from forex_agent.application.use_cases.forecast_performance_inspection_support import (
    require_valid_limit,
)
from forex_agent.domain.forecast_performance_inspection_mode import (
    ForecastPerformanceInspectionMode,
)
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class ForecastPerformanceSnapshotKeyPage:
    snapshot_keys: tuple[str, ...]
    next_cursor: str | None


class ListForecastPerformanceSnapshots:
    def __init__(self, performance_repository: ForecastPerformanceRepository) -> None:
        self._performance_repository = performance_repository

    async def __call__(
        self,
        mode: ForecastPerformanceInspectionMode,
        as_of: UtcTimestamp,
        *,
        cohort_key: str | None = None,
        limit: int,
        after_key: str | None = None,
    ) -> ForecastPerformanceSnapshotKeyPage:
        require_valid_limit(limit)
        keys = await self._performance_repository.list_distinct_snapshot_keys(
            mode=mode, as_of=as_of, cohort_key=cohort_key, limit=limit, after_key=after_key
        )
        next_cursor = keys[-1] if len(keys) == limit else None
        return ForecastPerformanceSnapshotKeyPage(snapshot_keys=keys, next_cursor=next_cursor)
