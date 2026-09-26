from enum import Enum
from typing import Protocol

from forex_agent.domain.economic_event_actual_value_vintage import (
    EconomicEventActualValueVintage,
)
from forex_agent.domain.economic_event_consensus_vintage import EconomicEventConsensusVintage
from forex_agent.domain.economic_event_occurrence import EconomicEventOccurrence
from forex_agent.domain.economic_event_schedule_vintage import EconomicEventScheduleVintage
from forex_agent.domain.timestamps import UtcTimestamp


class VintageWriteOutcome(Enum):
    """What an `add_*` write actually did (FX-51). Deliberately a
    separate, identically-shaped enum from `application.ports.
    macro_observation_repository.VintageWriteOutcome` (FX-43H) rather
    than an import across two otherwise-independent ports -- the
    concept is generic (idempotent-write outcome), but the two ports
    are not coupled to each other, and this duplication is two enum
    members, not a maintenance burden.

    Both outcomes are SUCCESSFUL, non-error results -- every `add_*`
    method remains idempotent for an exact retry either way.
    """

    INSERTED = "INSERTED"
    ALREADY_PRESENT = "ALREADY_PRESENT"


class EconomicEventOccurrenceConflictError(Exception):
    """Raised by `add_occurrence` when an occurrence with the same
    natural identity -- `(indicator_key, reference_period)` -- already
    exists in storage but its `release_group_key` differs from the
    incoming one. An exact duplicate is NOT an error (idempotent, see
    `add_occurrence`); only a genuine content mismatch is."""

    def __init__(
        self, existing: EconomicEventOccurrence, incoming: EconomicEventOccurrence
    ) -> None:
        self.existing = existing
        self.incoming = incoming
        super().__init__(
            "occurrence identity "
            f"(indicator_key={incoming.indicator_key!r}, "
            f"reference_period={incoming.reference_period.value.isoformat()!r}) already "
            f"exists with a different release_group_key: existing={existing!r}, "
            f"incoming={incoming!r}"
        )


class EconomicEventVintageConflictError(Exception):
    """Raised by `add_schedule_vintage`/`add_consensus_vintage`/
    `add_actual_value_vintage` when a vintage with the same natural
    identity -- `(indicator_key, reference_period, revision_sequence)`
    -- already exists in storage but its payload differs from the
    incoming one (mirrors `MacroVintageConflictError`, FX-41H, shared
    across all three FX-51 vintage kinds rather than duplicated three
    times -- the three vintage types are different dataclasses, but
    this error's own shape and meaning are identical for all three, so
    one generic error class is the honest representation, not three
    near-identical ones).

    This is a data-integrity failure, not something to retry or
    silently drop -- an exact duplicate of an already-stored vintage
    is NOT an error (see each `add_*` method's own idempotency
    requirement); only a genuine content mismatch is.
    """

    def __init__(
        self,
        existing: EconomicEventScheduleVintage
        | EconomicEventConsensusVintage
        | EconomicEventActualValueVintage,
        incoming: EconomicEventScheduleVintage
        | EconomicEventConsensusVintage
        | EconomicEventActualValueVintage,
    ) -> None:
        self.existing = existing
        self.incoming = incoming
        super().__init__(
            "vintage identity "
            f"(indicator_key={incoming.indicator_key!r}, "
            f"reference_period={incoming.reference_period.value.isoformat()!r}, "
            f"revision_sequence={incoming.revision_sequence}) already exists with a "
            f"different payload: existing={existing!r}, incoming={incoming!r}"
        )


class EconomicEventRepository(Protocol):
    """Port for storing and point-in-time-querying scheduled economic
    events (FX-51) -- occurrences, and their schedule/consensus/
    actual-value vintage histories.

    The defining invariant of every `*_as_of` method: a query at `as_of`
    must never return a vintage whose `availability` is `None` (i.e.
    `AvailabilityConfidence.UNKNOWN`) or after `as_of`. No provider/
    calendar-vendor logic belongs behind this port -- a concrete
    implementation only ever receives already-constructed domain
    objects; translating a specific provider's calendar response into
    one is FX-52's job, not this port's.
    """

    async def add_occurrence(self, occurrence: EconomicEventOccurrence) -> VintageWriteOutcome:
        """Persist a new occurrence. Idempotent for an exact retry;
        raises `EconomicEventOccurrenceConflictError` for a same-identity,
        different-`release_group_key` write. An occurrence must exist
        before any vintage of it can be added (enforced by a database
        foreign key in the SQL implementation, not merely by
        convention)."""
        ...

    async def get_occurrence(
        self, indicator_key: str, reference_period: UtcTimestamp
    ) -> EconomicEventOccurrence | None:
        """The occurrence at this natural identity, or `None` if it
        does not exist. Not point-in-time filtered -- an occurrence's
        own existence and `release_group_key` are not vintaged facts
        (see `EconomicEventOccurrence`'s own docstring)."""
        ...

    async def list_occurrences_for_indicator(
        self, indicator_key: str
    ) -> tuple[EconomicEventOccurrence, ...]:
        """Every occurrence of `indicator_key`, in no particular
        guaranteed order -- an administrative/batch read (mirrors
        `MacroObservationRepository.list_all_for_series`, FX-44), not a
        point-in-time query."""
        ...

    async def add_schedule_vintage(
        self, vintage: EconomicEventScheduleVintage
    ) -> VintageWriteOutcome:
        """Persist a new schedule vintage. Never mutates or replaces an
        existing one -- a reschedule/postponement/cancellation/
        reinstatement is a new vintage with a later `availability` and
        a higher `revision_sequence`. Idempotent for an exact retry;
        raises `EconomicEventVintageConflictError` for a same-identity,
        different-payload write."""
        ...

    async def add_consensus_vintage(
        self, vintage: EconomicEventConsensusVintage
    ) -> VintageWriteOutcome:
        """Persist a new consensus vintage. Same immutability/
        idempotency contract as `add_schedule_vintage`."""
        ...

    async def add_actual_value_vintage(
        self, vintage: EconomicEventActualValueVintage
    ) -> VintageWriteOutcome:
        """Persist a new actual-value vintage. Same immutability/
        idempotency contract as `add_schedule_vintage` -- a first
        release is never overwritten by a later revision; a revision
        is always a new row."""
        ...

    async def list_all_schedule_vintages(
        self, indicator_key: str, reference_period: UtcTimestamp
    ) -> tuple[EconomicEventScheduleVintage, ...]:
        """Every stored schedule vintage of this occurrence, in no
        particular guaranteed order -- an administrative/audit read,
        not a point-in-time query."""
        ...

    async def list_all_consensus_vintages(
        self, indicator_key: str, reference_period: UtcTimestamp
    ) -> tuple[EconomicEventConsensusVintage, ...]:
        """Every stored consensus vintage of this occurrence -- see
        `list_all_schedule_vintages`."""
        ...

    async def list_all_actual_value_vintages(
        self, indicator_key: str, reference_period: UtcTimestamp
    ) -> tuple[EconomicEventActualValueVintage, ...]:
        """Every stored actual-value vintage of this occurrence -- see
        `list_all_schedule_vintages`."""
        ...

    async def schedule_as_of(
        self, indicator_key: str, reference_period: UtcTimestamp, as_of: UtcTimestamp
    ) -> EconomicEventScheduleVintage | None:
        """The schedule state known as of `as_of` -- the latest
        schedule vintage of this occurrence with a defensibly-known
        `availability <= as_of`. `None` if none qualifies (including
        when every vintage's availability is unknown)."""
        ...

    async def consensus_as_of(
        self, indicator_key: str, reference_period: UtcTimestamp, as_of: UtcTimestamp
    ) -> EconomicEventConsensusVintage | None:
        """The consensus value known as of `as_of` -- see
        `schedule_as_of` for the shared visibility rule."""
        ...

    async def actual_value_as_of(
        self, indicator_key: str, reference_period: UtcTimestamp, as_of: UtcTimestamp
    ) -> EconomicEventActualValueVintage | None:
        """The actual value known as of `as_of`, in its most
        up-to-date form BY that instant (may already be a revision) --
        see `schedule_as_of` for the shared visibility rule."""
        ...

    async def first_release_as_of(
        self, indicator_key: str, reference_period: UtcTimestamp, as_of: UtcTimestamp
    ) -> EconomicEventActualValueVintage | None:
        """The FIRST release (`revision_sequence == 0`) specifically,
        still gated on `as_of` -- distinct from `actual_value_as_of`,
        which may already return a later revision. `None` if the first
        release does not exist yet, or exists but its own `availability`
        is after `as_of` or unknown."""
        ...

    async def known_events_in_window(
        self, start: UtcTimestamp, end: UtcTimestamp, as_of: UtcTimestamp
    ) -> tuple[tuple[EconomicEventOccurrence, EconomicEventScheduleVintage], ...]:
        """Every occurrence whose schedule state known as of `as_of`
        places it within `[start, end)` -- FX-51 Section 14's "get_
        known_events(start, end, as_of)" contract: "what economic
        events did the system know were scheduled at historical time
        T, within this window?" Each result pairs an occurrence with
        the SAME schedule vintage `schedule_as_of` would return for it
        individually -- this method is not a substitute for per-
        occurrence PIT correctness, it is the SAME rule applied across
        every occurrence in one query. An occurrence whose only known-
        as-of-`as_of` schedule falls outside `[start, end)` (or one with
        no schedule vintage known as of `as_of` at all) is excluded.
        """
        ...
