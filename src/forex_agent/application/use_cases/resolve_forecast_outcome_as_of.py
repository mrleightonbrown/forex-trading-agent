"""FX-65 Section 6/13: `ResolveForecastOutcomeAsOf` -- resolves the
outcome vintage permitted by an explicit `OutcomeVintageSelectionPolicy`
at an explicit PIT instant, never a final/latest-ever value regardless
of timing. See `ForecastOutcomeResolutionStatus` for the exact, honest
distinction this draws between "never recorded" (`OUTCOME_UNAVAILABLE`)
and "recorded, but not yet as of the requested instant" (`NOT_YET_
MATURED`) -- the latter is only distinguishable in retrospect, once at
least one vintage has actually been recorded for this `outcome_key`."""

from dataclasses import dataclass

from forex_agent.application.ports.forecast_outcome_repository import ForecastOutcomeRepository
from forex_agent.domain.forecast_outcome_resolution_status import ForecastOutcomeResolutionStatus
from forex_agent.domain.forecast_outcome_vintage import ForecastOutcomeVintage
from forex_agent.domain.outcome_vintage_selection_policy import OutcomeVintageSelectionPolicy
from forex_agent.domain.timestamps import UtcTimestamp


def _sort_key(vintage: ForecastOutcomeVintage) -> tuple[object, int]:
    return (vintage.availability.value, vintage.revision_sequence)


@dataclass(frozen=True, slots=True)
class ForecastOutcomeResolutionResult:
    status: ForecastOutcomeResolutionStatus
    vintage: ForecastOutcomeVintage | None
    """Non-`None` iff `status is OUTCOME_AVAILABLE`."""


class ResolveForecastOutcomeAsOf:
    def __init__(self, repository: ForecastOutcomeRepository) -> None:
        self._repository = repository

    async def __call__(
        self,
        outcome_key: str,
        policy: OutcomeVintageSelectionPolicy,
        as_of: UtcTimestamp,
        *,
        fixed_revision_sequence: int | None = None,
    ) -> ForecastOutcomeResolutionResult:
        history = await self._repository.list_vintages_for_outcome(outcome_key)
        if not history:
            return ForecastOutcomeResolutionResult(
                ForecastOutcomeResolutionStatus.OUTCOME_UNAVAILABLE, None
            )

        if policy is OutcomeVintageSelectionPolicy.FIRST_RELEASE:
            first = next((v for v in history if v.revision_sequence == 0), None)
            if first is None or first.availability.value > as_of.value:
                return ForecastOutcomeResolutionResult(
                    ForecastOutcomeResolutionStatus.NOT_YET_MATURED, None
                )
            return ForecastOutcomeResolutionResult(
                ForecastOutcomeResolutionStatus.OUTCOME_AVAILABLE, first
            )

        if policy is OutcomeVintageSelectionPolicy.LATEST_AVAILABLE_AS_OF:
            eligible = [v for v in history if v.availability.value <= as_of.value]
            if not eligible:
                return ForecastOutcomeResolutionResult(
                    ForecastOutcomeResolutionStatus.NOT_YET_MATURED, None
                )
            return ForecastOutcomeResolutionResult(
                ForecastOutcomeResolutionStatus.OUTCOME_AVAILABLE, max(eligible, key=_sort_key)
            )

        if policy is OutcomeVintageSelectionPolicy.FIXED_RELEASE_VINTAGE:
            if fixed_revision_sequence is None:
                return ForecastOutcomeResolutionResult(
                    ForecastOutcomeResolutionStatus.OUTCOME_AMBIGUOUS, None
                )
            match = next(
                (v for v in history if v.revision_sequence == fixed_revision_sequence), None
            )
            if match is None or match.availability.value > as_of.value:
                return ForecastOutcomeResolutionResult(
                    ForecastOutcomeResolutionStatus.NOT_YET_MATURED, None
                )
            return ForecastOutcomeResolutionResult(
                ForecastOutcomeResolutionStatus.OUTCOME_AVAILABLE, match
            )

        raise TypeError(f"policy must be an OutcomeVintageSelectionPolicy, got {policy!r}")
