"""FX-67 Section 4/12: shared, read-only support for every inspection
use case below -- NOT a use case itself, just the ONE place the
"which snapshot vintage does this inspection mean" question is
answered, so Production/Retrospective-research PIT dispatch (Section
12's own "no implicit fallback between production and retrospective
collections" rule) is implemented exactly once rather than once per
inspection entry point.

**FX-67H correction**: `ForecastPerformanceInspectionMode` moved to
`domain.forecast_performance_inspection_mode` (mirroring `Forecast
ProvenanceMode`'s own cross-cutting placement) once `list_distinct_
snapshot_keys` needed it on the `ForecastPerformanceRepository` PORT
itself -- a port depending on a type defined in an application USE
CASE module would be a backwards layering dependency. Every call site
now imports it directly from `domain`, never from here."""

from dataclasses import dataclass

from forex_agent.application.ports.forecast_performance_repository import (
    ForecastPerformanceRepository,
)
from forex_agent.domain.forecast_performance_inspection_mode import (
    ForecastPerformanceInspectionMode,
)
from forex_agent.domain.forecast_performance_snapshot import ForecastPerformanceSnapshot
from forex_agent.domain.timestamps import UtcTimestamp


async def resolve_snapshot_for_inspection(
    repository: ForecastPerformanceRepository,
    snapshot_key: str,
    mode: ForecastPerformanceInspectionMode,
    as_of: UtcTimestamp,
) -> ForecastPerformanceSnapshot | None:
    """`None` iff no vintage of `snapshot_key` was visible, under
    `mode`'s own read path, by `as_of` -- a snapshot recorded AFTER
    `as_of` (Section 12's own "a snapshot recorded in 2026 cannot
    appear in a query asking what FTA had recorded in 2024" rule) is
    indistinguishable from one that never existed, by construction of
    the underlying FX-66 PIT read methods this delegates to unchanged."""
    if mode is ForecastPerformanceInspectionMode.PRODUCTION:
        return await repository.latest_production_observed_snapshot_as_of(snapshot_key, as_of)
    return await repository.latest_snapshot_as_of_for_research(snapshot_key, as_of)


@dataclass(frozen=True, slots=True)
class UnresolvedEvidenceReference:
    """FX-67 Section 6: an EXPLICIT integrity diagnostic -- a snapshot
    member/evaluation pinned a `(key, revision_sequence)` that could
    not be resolved against the live repository. Displayed AS-IS
    rather than silently hidden or replaced with invented/current
    data (Section 6's own explicit "do not silently hide unresolved
    references" rule). This should never actually occur against
    correctly-functioning upstream writers (every pinning reference
    is created from evidence that existed at write time), but
    inspection code must handle it explicitly rather than crash or
    fabricate a substitute."""

    what: str
    key: str
    revision_sequence: int


class InvalidInspectionPageBoundsError(Exception):
    """FX-67 Section 14/20.F: `limit` must be a positive int -- a
    zero/negative/non-int bound is rejected explicitly, never
    silently clamped or treated as "unbounded" (Section 14's own "do
    not perform an unbounded full-table scan" rule)."""

    def __init__(self, limit: object) -> None:
        self.limit = limit
        super().__init__(f"limit must be a positive int, got {limit!r}")


def require_valid_limit(limit: int) -> None:
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise InvalidInspectionPageBoundsError(limit)


def find_exact_version[T](
    versions: tuple[T, ...], version_sequence: int, *, version_field: str = "version_sequence"
) -> T | None:
    """Shared "find this exact pinned version among every version
    this key has ever had" lookup -- mirrors `BuildForecastPerformance
    PopulationAsOf._resolve_forecast_vintage`'s own exact-revision-
    match pattern, generalized over whichever append-only-version type
    is being searched (cohort/methodology/benchmark/protocol/outcome
    definition all share this exact shape)."""
    return next(
        (v for v in versions if getattr(v, version_field) == version_sequence),
        None,
    )
