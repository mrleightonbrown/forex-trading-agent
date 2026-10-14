"""FX-65 Section 13: `GetForecastEvaluationAsOf` -- the ONLY production
PIT read for a single evaluation. Thin wrapper over `ForecastEvaluation
Repository.latest_production_observed_evaluation_as_of`, mirroring
FX-64's own `GetForecastClaimAsOf` exactly."""

from dataclasses import dataclass
from enum import Enum

from forex_agent.application.ports.forecast_evaluation_repository import (
    ForecastEvaluationRepository,
)
from forex_agent.domain.structured_forecast_evaluation_vintage import (
    StructuredForecastEvaluationVintage,
)
from forex_agent.domain.timestamps import UtcTimestamp


class ForecastEvaluationResolution(Enum):
    KNOWN = "KNOWN"
    NOT_KNOWN = "NOT_KNOWN"


@dataclass(frozen=True, slots=True)
class ForecastEvaluationResolutionResult:
    resolution: ForecastEvaluationResolution
    vintage: StructuredForecastEvaluationVintage | None
    """`None` iff `resolution is NOT_KNOWN`."""


class GetForecastEvaluationAsOf:
    def __init__(self, repository: ForecastEvaluationRepository) -> None:
        self._repository = repository

    async def __call__(
        self, evaluation_key: str, as_of: UtcTimestamp
    ) -> ForecastEvaluationResolutionResult:
        vintage = await self._repository.latest_production_observed_evaluation_as_of(
            evaluation_key, as_of
        )
        if vintage is None:
            return ForecastEvaluationResolutionResult(ForecastEvaluationResolution.NOT_KNOWN, None)
        return ForecastEvaluationResolutionResult(ForecastEvaluationResolution.KNOWN, vintage)
