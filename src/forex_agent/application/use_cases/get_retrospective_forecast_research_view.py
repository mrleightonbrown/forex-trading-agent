"""FX-64 Section 7/14: `GetRetrospectiveForecastResearchView` -- the
ONE explicit, separately-selected read path that may return a
`RETROSPECTIVE_RESEARCH` vintage. Never confusable with `GetForecast
ClaimAsOf`: this use case requires its OWN `research_as_of` parameter
(never named `as_of`, and never reachable by passing a research flag
to the production read) and its result makes BOTH the vintage's own
`availability` (FTA's actual discovery/registration instant) and
`original_publication_at` (the TRUE original publication instant, if
known) explicit and visible -- a caller can never mistake one for the
other, and this view NEVER claims FTA knew the forecast any earlier
than its own `availability`."""

from dataclasses import dataclass

from forex_agent.application.ports.structured_forecast_repository import (
    StructuredForecastRepository,
)
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.structured_forecast_vintage import StructuredForecastVintage
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class RetrospectiveForecastResearchResult:
    vintage: StructuredForecastVintage | None
    """`None` if nothing is known for this claim as of `research_
    as_of`, under EITHER provenance mode."""

    @property
    def is_retrospective(self) -> bool:
        """`True` iff the resolved vintage is itself `RETROSPECTIVE_
        RESEARCH` -- a caller inspecting this result can always tell
        whether the forecast it received was ever genuinely available
        to FTA's own production pipeline."""
        return (
            self.vintage is not None
            and self.vintage.provenance_mode is ForecastProvenanceMode.RETROSPECTIVE_RESEARCH
        )


class GetRetrospectiveForecastResearchView:
    def __init__(self, repository: StructuredForecastRepository) -> None:
        self._repository = repository

    async def __call__(
        self, claim_key: str, research_as_of: UtcTimestamp
    ) -> RetrospectiveForecastResearchResult:
        vintage = await self._repository.latest_vintage_as_of_for_research(
            claim_key, research_as_of
        )
        return RetrospectiveForecastResearchResult(vintage)
