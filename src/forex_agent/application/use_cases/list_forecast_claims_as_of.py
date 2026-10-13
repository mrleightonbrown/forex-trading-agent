"""FX-64 Section 14: `ListForecastClaimsAsOf` -- the batch production
PIT read. Thin wrapper over `StructuredForecastRepository.list_
production_observed_claims_as_of`, which is the ONLY batch repository
method, and which (like its single-claim sibling) can NEVER return a
`RETROSPECTIVE_RESEARCH` vintage."""

from dataclasses import dataclass

from forex_agent.application.ports.structured_forecast_repository import (
    StructuredForecastRepository,
)
from forex_agent.domain.structured_forecast_vintage import StructuredForecastVintage
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class ForecastClaimsListResult:
    vintages: tuple[StructuredForecastVintage, ...]
    """One per claim -- each claim's own latest `PRODUCTION_OBSERVED`
    vintage with `availability <= as_of`."""


class ListForecastClaimsAsOf:
    def __init__(self, repository: StructuredForecastRepository) -> None:
        self._repository = repository

    async def __call__(
        self,
        as_of: UtcTimestamp,
        *,
        target_key: str | None = None,
        window_start: UtcTimestamp | None = None,
        window_end: UtcTimestamp | None = None,
    ) -> ForecastClaimsListResult:
        vintages = await self._repository.list_production_observed_claims_as_of(
            as_of, target_key=target_key, window_start=window_start, window_end=window_end
        )
        return ForecastClaimsListResult(vintages)
