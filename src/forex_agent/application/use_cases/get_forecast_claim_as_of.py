"""FX-64 Section 14: `GetForecastClaimAsOf` -- the ONLY production
PIT read for a single claim. Thin wrapper over `StructuredForecast
Repository.latest_production_observed_vintage_as_of`, which itself is
the ONLY repository method that filters to `PRODUCTION_OBSERVED` --
see that port's own module docstring for the full production-versus-
research separation this exists to protect."""

from dataclasses import dataclass
from enum import Enum

from forex_agent.application.ports.structured_forecast_repository import (
    StructuredForecastRepository,
)
from forex_agent.domain.structured_forecast_vintage import StructuredForecastVintage
from forex_agent.domain.timestamps import UtcTimestamp


class ForecastClaimResolution(Enum):
    KNOWN = "KNOWN"
    NOT_KNOWN = "NOT_KNOWN"


@dataclass(frozen=True, slots=True)
class ForecastClaimResolutionResult:
    resolution: ForecastClaimResolution
    vintage: StructuredForecastVintage | None
    """`None` iff `resolution is NOT_KNOWN`."""


class GetForecastClaimAsOf:
    def __init__(self, repository: StructuredForecastRepository) -> None:
        self._repository = repository

    async def __call__(self, claim_key: str, as_of: UtcTimestamp) -> ForecastClaimResolutionResult:
        vintage = await self._repository.latest_production_observed_vintage_as_of(claim_key, as_of)
        if vintage is None:
            return ForecastClaimResolutionResult(ForecastClaimResolution.NOT_KNOWN, None)
        return ForecastClaimResolutionResult(ForecastClaimResolution.KNOWN, vintage)
