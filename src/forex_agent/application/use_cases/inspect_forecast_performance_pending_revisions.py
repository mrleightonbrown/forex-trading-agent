"""FX-66H.1 (H1/F66-04): `InspectForecastPerformancePendingRevisions`
-- a SEPARATE, READ-ONLY administrative diagnostic answering "which
ACCEPTED members of a HISTORICAL population (as of `historical_
cutoff`) have since had a newer evaluation revision become available
by `administrative_as_of`."

This is explicitly NOT part of `BuildForecastPerformancePopulationAsOf`
-- that use case's own result must stay byte-for-byte reproducible for
a fixed cutoff no matter what is appended later (F66-04's own
requirement). This use case instead answers a DIFFERENT, explicitly
forward-looking question, with its OWN explicit `administrative_as_of`
parameter (never `now()` computed internally), and its result is never
read by `RecordForecastPerformanceSnapshot` or persisted as part of
any snapshot -- it exists purely for a human/administrative audit
view ("has anything changed since we last looked at this cohort").

Reuses `BuildForecastPerformancePopulationAsOf` TWICE (once per
cutoff) rather than inventing a new repository method or re-deriving
structural eligibility -- the exact same PIT-bounded selection this
epic's own H1 fix already established is reused unchanged for both
reads, so there is only ever ONE population-selection algorithm."""

from dataclasses import dataclass

from forex_agent.application.use_cases.build_forecast_performance_population_as_of import (
    BuildForecastPerformancePopulationAsOf,
)
from forex_agent.domain.forecast_performance_cohort_definition import (
    ForecastPerformanceCohortDefinition,
)
from forex_agent.domain.timestamps import UtcTimestamp


class InvalidAdministrativeInspectionWindowError(Exception):
    """`administrative_as_of` must not be earlier than `historical_
    cutoff` -- inspecting "what changed since the cutoff" makes no
    sense over a window that runs backwards."""

    def __init__(self, historical_cutoff: UtcTimestamp, administrative_as_of: UtcTimestamp) -> None:
        self.historical_cutoff = historical_cutoff
        self.administrative_as_of = administrative_as_of
        super().__init__(
            f"administrative_as_of={administrative_as_of.value.isoformat()} must not be earlier "
            f"than historical_cutoff={historical_cutoff.value.isoformat()}"
        )


@dataclass(frozen=True, slots=True)
class ForecastPerformancePendingRevisionReport:
    cohort_key: str
    historical_cutoff: UtcTimestamp
    administrative_as_of: UtcTimestamp
    pending_evaluation_keys: tuple[str, ...]
    """`evaluation_key`s that WERE accepted into the historical
    population at `historical_cutoff`, for which a strictly newer
    revision has since become available by `administrative_as_of`.
    Purely informational -- never affects any persisted result."""


class InspectForecastPerformancePendingRevisions:
    def __init__(self, build_population: BuildForecastPerformancePopulationAsOf) -> None:
        self._build_population = build_population

    async def __call__(
        self,
        cohort: ForecastPerformanceCohortDefinition,
        *,
        historical_cutoff: UtcTimestamp,
        administrative_as_of: UtcTimestamp,
    ) -> ForecastPerformancePendingRevisionReport:
        if administrative_as_of.value < historical_cutoff.value:
            raise InvalidAdministrativeInspectionWindowError(
                historical_cutoff, administrative_as_of
            )

        historical = await self._build_population(cohort, historical_cutoff)
        administrative = await self._build_population(cohort, administrative_as_of)
        administrative_revisions = {
            m.evaluation.evaluation_key: m.evaluation.revision_sequence
            for m in administrative.accepted
        }

        pending = tuple(
            m.evaluation.evaluation_key
            for m in historical.accepted
            if administrative_revisions.get(
                m.evaluation.evaluation_key, m.evaluation.revision_sequence
            )
            > m.evaluation.revision_sequence
        )
        return ForecastPerformancePendingRevisionReport(
            cohort_key=cohort.cohort_key,
            historical_cutoff=historical_cutoff,
            administrative_as_of=administrative_as_of,
            pending_evaluation_keys=pending,
        )
