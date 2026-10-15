"""FX-66 Section 13/17: `GetRetrospectiveForecastPerformanceResearchView`
-- the ONE explicit, separately-selected read path that may return a
`RETROSPECTIVE_RESEARCH` snapshot. Never confusable with `GetForecast
PerformanceSnapshotAsOf`: requires its OWN `research_as_of` parameter
(never `as_of`), mirroring `GetRetrospectiveForecastEvaluation`
exactly."""

from dataclasses import dataclass

from forex_agent.application.ports.forecast_performance_repository import (
    ForecastPerformanceRepository,
)
from forex_agent.domain.forecast_performance_snapshot import ForecastPerformanceSnapshot
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class RetrospectiveForecastPerformanceResult:
    snapshot: ForecastPerformanceSnapshot | None
    """`None` if nothing is known for this snapshot_key as of
    `research_as_of`, under EITHER evaluation mode."""

    @property
    def is_retrospective(self) -> bool:
        return (
            self.snapshot is not None
            and self.snapshot.evaluation_mode is ForecastProvenanceMode.RETROSPECTIVE_RESEARCH
        )


class GetRetrospectiveForecastPerformanceResearchView:
    def __init__(self, repository: ForecastPerformanceRepository) -> None:
        self._repository = repository

    async def __call__(
        self, snapshot_key: str, research_as_of: UtcTimestamp
    ) -> RetrospectiveForecastPerformanceResult:
        snapshot = await self._repository.latest_snapshot_as_of_for_research(
            snapshot_key, research_as_of
        )
        return RetrospectiveForecastPerformanceResult(snapshot)
