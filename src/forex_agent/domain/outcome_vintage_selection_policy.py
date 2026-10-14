from enum import Enum


class OutcomeVintageSelectionPolicy(Enum):
    """FX-65 Section 6: which outcome vintage an evaluation protocol is
    permitted to use -- frozen on the protocol itself BEFORE evaluation,
    never chosen afterward to make a particular forecast look accurate
    (Section 7's own explicit prohibition)."""

    FIRST_RELEASE = "FIRST_RELEASE"
    """The outcome's own `revision_sequence == 0` vintage, once it
    becomes available -- never silently replaced by a later revision,
    even after one is recorded."""

    LATEST_AVAILABLE_AS_OF = "LATEST_AVAILABLE_AS_OF"
    """Whichever outcome revision has the highest `(availability,
    revision_sequence)` not exceeding the requested PIT instant --
    SELECTED ONLY from revisions genuinely available at that instant,
    never a final/latest-ever value regardless of timing."""

    FIXED_RELEASE_VINTAGE = "FIXED_RELEASE_VINTAGE"
    """An exact, protocol-pinned `revision_sequence` -- the protocol
    itself names which one; still PIT-filtered (a pinned revision that
    has not yet become available as of the requested instant resolves
    to `NOT_YET_MATURED`, never leaked from the future)."""
