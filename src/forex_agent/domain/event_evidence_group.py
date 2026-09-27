"""FX-54: one release package's worth of evidence -- e.g. BLS's
"Employment Situation" release, which represents `US_NONFARM_PAYROLLS`
and `US_UNEMPLOYMENT_RATE` as two separate canonical occurrences
sharing one `EconomicEventOccurrence.release_group_key` (FX-51 Section
11's own worked example). This type exists so a consumer can tell "one
release package, two canonical measurements" apart from "two
unrelated, simultaneous events" (FX-54 Section 16) without either
collapsing the members into one indicator (losing individual canonical
identity) or inventing a group-level fact (a "primary" member, a
shared exact time) that does not genuinely exist.

Deliberately generic (`EventEvidenceGroup[T]`, matching this project's
own existing PEP 695 generic-function convention already established
in `domain.economic_event_state`) rather than two near-identical
concrete types -- the SAME "grouped members, no aggregate fact"
shape applies equally to `EventScheduleEvidence` and
`EventReleaseEvidence`; only the member type differs.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EventEvidenceGroup[T]:
    """`group_key` is `EconomicEventOccurrence.release_group_key` when
    the occurrence has one, or that occurrence's own `occurrence_key`
    otherwise (FX-54 Section 16: "for an occurrence with no
    release_group_key, treat that one occurrence as its own one-member
    group") -- always non-empty, so every occurrence is represented by
    exactly one group either way. `members` is never empty and is
    sorted deterministically by its own builder (see `domain.
    event_schedule_evidence.group_schedule_evidence`/`domain.
    event_release_evidence.group_release_evidence`) -- this type
    itself carries no ranking, no "primary" member, and no aggregate
    group-level time: there is structurally nowhere on this type to
    invent one (FX-54 Section 17)."""

    group_key: str
    members: tuple[T, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.group_key, str) or not self.group_key.strip():
            raise ValueError(f"group_key must be a non-empty string, got {self.group_key!r}")
        if not isinstance(self.members, tuple) or not self.members:
            raise ValueError("members must be a non-empty tuple")
