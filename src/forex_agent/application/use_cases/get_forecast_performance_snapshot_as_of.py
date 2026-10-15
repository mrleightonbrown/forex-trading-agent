"""FX-66 Section 17: `GetForecastPerformanceSnapshotAsOf` -- the ONE
production PIT read path. Mirrors `GetForecastEvaluationAsOf`/`Get
RetrospectiveForecastEvaluation`'s own production-versus-research
read-path separation exactly: never returns a `RETROSPECTIVE_
RESEARCH` snapshot, regardless of `as_of`."""

from dataclasses import dataclass

from forex_agent.application.ports.forecast_performance_repository import (
    ForecastPerformanceRepository,
)
from forex_agent.domain.forecast_performance_snapshot import ForecastPerformanceSnapshot
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class ForecastPerformanceSnapshotResolution:
    snapshot: ForecastPerformanceSnapshot | None
    """`None` if nothing is known for this snapshot_key as of `as_of`
    under `PRODUCTION_OBSERVED` mode."""


class GetForecastPerformanceSnapshotAsOf:
    def __init__(self, repository: ForecastPerformanceRepository) -> None:
        self._repository = repository

    async def __call__(
        self, snapshot_key: str, as_of: UtcTimestamp
    ) -> ForecastPerformanceSnapshotResolution:
        snapshot = await self._repository.latest_production_observed_snapshot_as_of(
            snapshot_key, as_of
        )
        return ForecastPerformanceSnapshotResolution(snapshot)
