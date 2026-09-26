"""FX-51 Section 14's "get_event_state(event_id, as_of)" contract: what
did the system know about one specific occurrence's schedule/consensus/
actual value/release at historical instant `as_of`, assembled from its
complete vintage histories via the repository's own `*_as_of` methods --
each of which already enforces the point-in-time invariant at the SQL
layer (`application.ports.economic_event_repository.EconomicEventRepository`).

This use case does no PIT logic of its own -- it is pure orchestration,
the same division of labour `ComputePolicyRateDifferential` (FX-45)
already established: the repository answers "what does storage say
about a single instant," this use case's only job is to ask it five
times (schedule/consensus/actual/first-release/release) for the SAME
occurrence and the SAME `as_of`, and hand back one combined result
rather than requiring every caller to make five separate calls itself.

FX-51H added the `release` field (via `release_as_of`) so a caller can
learn whether a qualitative/non-numeric occurrence has actually
happened, not only whether it has a numeric value -- and switched the
identifying parameter from `(indicator_key, reference_period)` to
`occurrence_key` alone, matching the identity model change.
"""

from dataclasses import dataclass

from forex_agent.application.ports.economic_event_repository import EconomicEventRepository
from forex_agent.domain.economic_event_actual_value_vintage import (
    EconomicEventActualValueVintage,
)
from forex_agent.domain.economic_event_consensus_vintage import EconomicEventConsensusVintage
from forex_agent.domain.economic_event_occurrence import EconomicEventOccurrence
from forex_agent.domain.economic_event_release_vintage import EconomicEventReleaseVintage
from forex_agent.domain.economic_event_schedule_vintage import EconomicEventScheduleVintage
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class EconomicEventState:
    """Everything known about one occurrence, as of one instant.

    Any of `schedule`/`consensus`/`actual`/`first_release`/`release`
    may be `None` -- this is never an error. A `None` schedule means no
    schedule vintage of this occurrence has known availability at or
    before `as_of` (it may not even be scheduled yet, as far as the
    system could know at `as_of`). A `None` consensus/actual is
    equally expected for a qualitative event (FX-51 Section 18) or for
    `as_of` before any consensus/release existed. A `None` `release`
    means the system did not yet know, as of `as_of`, that this
    occurrence had actually happened (FX-51H) -- true for every
    occurrence, numeric or qualitative, before its own release
    vintage's `availability`. Callers must treat each `None` as
    "unavailable as of this instant," never substitute a guessed
    value.
    """

    occurrence: EconomicEventOccurrence
    schedule: EconomicEventScheduleVintage | None
    consensus: EconomicEventConsensusVintage | None
    actual: EconomicEventActualValueVintage | None
    first_release: EconomicEventActualValueVintage | None
    release: EconomicEventReleaseVintage | None


class GetEconomicEventState:
    """FX-51's answer to "what did the system know about this
    occurrence at instant T" -- see the module docstring."""

    def __init__(self, repository: EconomicEventRepository) -> None:
        self._repository = repository

    async def __call__(self, occurrence_key: str, as_of: UtcTimestamp) -> EconomicEventState | None:
        """`None` if no occurrence exists at this `occurrence_key` at
        all -- distinct from an `EconomicEventState` whose individual
        fields are `None` because nothing about an EXISTING occurrence
        was yet knowable at `as_of`."""
        occurrence = await self._repository.get_occurrence(occurrence_key)
        if occurrence is None:
            return None
        schedule = await self._repository.schedule_as_of(occurrence_key, as_of)
        consensus = await self._repository.consensus_as_of(occurrence_key, as_of)
        actual = await self._repository.actual_value_as_of(occurrence_key, as_of)
        first_release = await self._repository.first_release_as_of(occurrence_key, as_of)
        release = await self._repository.release_as_of(occurrence_key, as_of)
        return EconomicEventState(
            occurrence=occurrence,
            schedule=schedule,
            consensus=consensus,
            actual=actual,
            first_release=first_release,
            release=release,
        )
