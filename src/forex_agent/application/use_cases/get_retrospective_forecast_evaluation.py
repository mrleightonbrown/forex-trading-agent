"""FX-65 Section 9/13: `GetRetrospectiveForecastEvaluation` -- the ONE
explicit, separately-selected read path that may return a `RETROSPECTIVE
_RESEARCH` evaluation. Never confusable with `GetForecastEvaluationAsOf`:
requires its OWN `research_as_of` parameter (never `as_of`), mirroring
FX-64's own `GetRetrospectiveForecastResearchView` exactly."""

from dataclasses import dataclass

from forex_agent.application.ports.forecast_evaluation_repository import (
    ForecastEvaluationRepository,
)
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.structured_forecast_evaluation_vintage import (
    StructuredForecastEvaluationVintage,
)
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class RetrospectiveForecastEvaluationResult:
    vintage: StructuredForecastEvaluationVintage | None
    """`None` if nothing is known for this evaluation as of `research_
    as_of`, under EITHER evaluation mode."""

    @property
    def is_retrospective(self) -> bool:
        return (
            self.vintage is not None
            and self.vintage.evaluation_mode is ForecastProvenanceMode.RETROSPECTIVE_RESEARCH
        )


class GetRetrospectiveForecastEvaluation:
    def __init__(self, repository: ForecastEvaluationRepository) -> None:
        self._repository = repository

    async def __call__(
        self, evaluation_key: str, research_as_of: UtcTimestamp
    ) -> RetrospectiveForecastEvaluationResult:
        vintage = await self._repository.latest_evaluation_as_of_for_research(
            evaluation_key, research_as_of
        )
        return RetrospectiveForecastEvaluationResult(vintage)
