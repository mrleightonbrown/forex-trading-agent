"""FX-67 Section 6/14: `GetForecastPerformanceMembers` -- paginated,
deterministically-ordered drill-down over ONE snapshot's own EXACT
accepted membership, reusing `GetForecastEvaluationInspection`
per-member rather than re-implementing its forecast/outcome/
attribution resolution a second time.

Ordered by `evaluation_key` ascending -- already a unique key within
one snapshot's own membership (duplicate-resolution already ran
before a member was ever accepted, FX-66 Section 7), so no secondary
tie-breaker is needed. Bounded by an explicit, mandatory `limit`
(Section 14's own "must be bounded" rule, enforced via `require_valid_
limit` -- never an unbounded scan)."""

from dataclasses import dataclass

from forex_agent.application.ports.forecast_evaluation_repository import (
    ForecastEvaluationRepository,
)
from forex_agent.application.ports.forecast_outcome_repository import ForecastOutcomeRepository
from forex_agent.application.ports.forecast_performance_repository import (
    ForecastPerformanceRepository,
)
from forex_agent.application.ports.source_registry_repository import SourceRegistryRepository
from forex_agent.application.ports.structured_forecast_repository import (
    StructuredForecastRepository,
)
from forex_agent.application.use_cases.forecast_performance_inspection_support import (
    UnresolvedEvidenceReference,
    require_valid_limit,
    resolve_snapshot_for_inspection,
)
from forex_agent.application.use_cases.get_forecast_evaluation_inspection import (
    ForecastEvaluationInspection,
    GetForecastEvaluationInspection,
)
from forex_agent.domain.forecast_performance_inspection_mode import (
    ForecastPerformanceInspectionMode,
)
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class ForecastPerformanceMemberPage:
    snapshot_key: str
    snapshot_revision_sequence: int
    members: tuple[ForecastEvaluationInspection | UnresolvedEvidenceReference, ...]
    next_cursor: str | None
    """The `evaluation_key` to pass as `after_key` for the next page,
    or `None` once the last page has been returned."""


class SnapshotNotVisibleForInspectionError(Exception):
    """No vintage of `snapshot_key` was visible, under `mode`, by
    `as_of` -- Section 12's own "a snapshot recorded in 2026 cannot
    appear in a query asking what FTA had recorded in 2024" rule,
    surfaced as an explicit error rather than an empty/ambiguous page."""

    def __init__(self, snapshot_key: str) -> None:
        self.snapshot_key = snapshot_key
        super().__init__(f"snapshot_key={snapshot_key!r} is not visible for this mode/as_of")


class GetForecastPerformanceMembers:
    def __init__(
        self,
        performance_repository: ForecastPerformanceRepository,
        evaluation_repository: ForecastEvaluationRepository,
        forecast_repository: StructuredForecastRepository,
        outcome_repository: ForecastOutcomeRepository,
        registry_repository: SourceRegistryRepository,
    ) -> None:
        self._performance_repository = performance_repository
        self._evaluation_inspection = GetForecastEvaluationInspection(
            evaluation_repository, forecast_repository, outcome_repository, registry_repository
        )

    async def __call__(
        self,
        snapshot_key: str,
        mode: ForecastPerformanceInspectionMode,
        as_of: UtcTimestamp,
        *,
        limit: int,
        after_key: str | None = None,
    ) -> ForecastPerformanceMemberPage:
        require_valid_limit(limit)
        snapshot = await resolve_snapshot_for_inspection(
            self._performance_repository, snapshot_key, mode, as_of
        )
        if snapshot is None:
            raise SnapshotNotVisibleForInspectionError(snapshot_key)

        ordered = sorted(snapshot.members, key=lambda m: m.evaluation_key)
        page = [m for m in ordered if after_key is None or m.evaluation_key > after_key][:limit]

        inspections = tuple(
            [
                await self._evaluation_inspection(
                    m.evaluation_key,
                    m.evaluation_revision_sequence,
                    attribution_as_of=snapshot.knowledge_cutoff,
                )
                for m in page
            ]
        )
        next_cursor = page[-1].evaluation_key if len(page) == limit else None
        return ForecastPerformanceMemberPage(
            snapshot_key=snapshot.snapshot_key,
            snapshot_revision_sequence=snapshot.revision_sequence,
            members=inspections,
            next_cursor=next_cursor,
        )
