"""FX-51: pure point-in-time state selection over an already-fetched
economic-event vintage history -- the domain-layer answer to "what did
the system know about this occurrence's schedule/consensus/actual value
at instant T," in exactly the shape `domain.policy_rate_state` (FX-45)
already established for policy-rate vintages: a caller (a future use
case) fetches one occurrence's complete vintage history once, then can
evaluate MULTIPLE point-in-time queries against it in memory rather
than re-querying storage per instant.

Every selection function here applies the SAME rule: a vintage is
visible at `as_of` if and only if its `availability` is not `None`
(equivalently, `availability_confidence` is not `AvailabilityConfidence.
UNKNOWN` -- the two are structurally tied, see `domain._guards.
require_availability_consistency`) AND `availability <= as_of`. A
vintage with unknown availability is never visible at ANY `as_of`, no
matter how far in the future -- FX-51 Section 13's fail-closed
requirement, enforced here rather than left to callers to remember.
"""

from collections.abc import Sequence

from forex_agent.domain.economic_event_actual_value_vintage import (
    EconomicEventActualValueVintage,
)
from forex_agent.domain.economic_event_consensus_vintage import EconomicEventConsensusVintage
from forex_agent.domain.economic_event_schedule_vintage import EconomicEventScheduleVintage
from forex_agent.domain.timestamps import UtcTimestamp

_HasAvailability = (
    EconomicEventScheduleVintage | EconomicEventConsensusVintage | EconomicEventActualValueVintage
)


def _available_as_of[T: _HasAvailability](vintages: Sequence[T], as_of: UtcTimestamp) -> list[T]:
    """Every vintage in `vintages` with a defensibly-known `availability
    <= as_of` -- the shared visibility filter every selection function
    below applies before picking a "latest" candidate."""
    return [
        v for v in vintages if v.availability is not None and v.availability.value <= as_of.value
    ]


def _latest[T: _HasAvailability](vintages: list[T]) -> T | None:
    """Among an already-`_available_as_of`-filtered list (so every
    entry's `availability` is guaranteed not `None`), the one with the
    greatest `(availability, revision_sequence)` -- the latest fact
    knowable, tie-broken deterministically by `revision_sequence` when
    two vintages share the same `availability` (mirrors
    `MacroObservationRepository`'s own `revision_sequence DESC`
    tie-break convention, FX-41H)."""
    if not vintages:
        return None

    def _key(v: T) -> tuple[object, int]:
        assert v.availability is not None  # guaranteed by _available_as_of's own filter
        return (v.availability.value, v.revision_sequence)

    return max(vintages, key=_key)


def latest_schedule_as_of(
    vintages: Sequence[EconomicEventScheduleVintage], as_of: UtcTimestamp
) -> EconomicEventScheduleVintage | None:
    """The schedule state (date/time/status) known as of `as_of` --
    FX-51's worked example A: schedule announced Jan 1, rescheduled
    Jan 5; `as_of` Jan 3 returns the Jan 1 vintage, `as_of` Jan 6
    returns the rescheduled one. `None` if no schedule vintage of this
    occurrence has known availability at or before `as_of`."""
    return _latest(_available_as_of(vintages, as_of))


def latest_consensus_as_of(
    vintages: Sequence[EconomicEventConsensusVintage], as_of: UtcTimestamp
) -> EconomicEventConsensusVintage | None:
    """The consensus value known as of `as_of` -- FX-51's worked
    example B: consensus 3.1 at 09:00, revised to 3.0 at 12:00, release
    13:30; `as_of` 11:00 returns 3.1, `as_of` 13:00 returns 3.0. A
    post-release consensus update never rewrites what an earlier
    `as_of` sees, since that update's own `availability` is later than
    any pre-release `as_of` being queried. `None` if no consensus
    vintage of this occurrence has known availability at or before
    `as_of`."""
    return _latest(_available_as_of(vintages, as_of))


def latest_actual_as_of(
    vintages: Sequence[EconomicEventActualValueVintage], as_of: UtcTimestamp
) -> EconomicEventActualValueVintage | None:
    """The actual value known as of `as_of`, in its most up-to-date
    form BY that instant -- FX-51's worked example C: first release
    150 at 13:30, revision to 140 published later; `as_of` 14:00 on
    release day returns 150 (the revision does not exist to know about
    yet), `as_of` after the revision's own availability returns 140.
    `None` if no actual-value vintage of this occurrence has known
    availability at or before `as_of`."""
    return _latest(_available_as_of(vintages, as_of))


def first_release_as_of(
    vintages: Sequence[EconomicEventActualValueVintage], as_of: UtcTimestamp
) -> EconomicEventActualValueVintage | None:
    """The FIRST release (`revision_sequence == 0`) specifically,
    still gated on `as_of` -- distinct from `latest_actual_as_of`,
    which returns whichever revision is latest BY `as_of` (that may
    already be a later revision). This is what FX-51 Section 5.5 calls
    "first-release remains recoverable": a later revision never
    replaces or hides the `revision_sequence == 0` row, so this
    function keeps answering the same way regardless of how many
    revisions have since been published, PROVIDED `as_of` is at or
    after the first release's own `availability` -- querying before
    that still correctly returns `None`, matching FX-51 Section 7's
    "actual_first_available" building block for a future surprise
    calculation.
    """
    available = _available_as_of(vintages, as_of)
    first = [v for v in available if v.revision_sequence == 0]
    return _latest(first)
