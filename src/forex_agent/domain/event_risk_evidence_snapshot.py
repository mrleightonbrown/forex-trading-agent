"""FX-54: the top-level, provider-neutral answer to "given this FX
pair, at this exact point in time, what economic-event timing evidence
did the system know?" -- assembled by `application.use_cases.
get_event_risk_evidence_snapshot.GetEventRiskEvidenceSnapshot`.

A pure, immutable value object: no I/O, no current-clock access, no
trade-policy method of any kind. It reports facts (schedule/release
timing evidence, structural coverage) and deliberately never a
verdict -- see `EventCoverageEvidence`'s own docstring for why an
empty evidence list here is never "safe," and the use case's own
module docstring for the full evidence/policy boundary this story
must not cross.
"""

from dataclasses import dataclass
from datetime import timedelta

from forex_agent.domain.event_coverage_evidence import EventCoverageEvidence
from forex_agent.domain.event_evidence_group import EventEvidenceGroup
from forex_agent.domain.event_release_evidence import EventReleaseEvidence
from forex_agent.domain.event_schedule_evidence import EventScheduleEvidence
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class EventRiskEvidenceSnapshot:
    """Fields:
    instrument: the requested FX pair, verbatim.
    as_of: the exact instant this snapshot answers for -- every
        fact inside it was knowable to the system at or before
        this instant (PIT-safe by construction, via the
        repository's own `*_as_of`/`known_*_in_window` methods).
    lookahead/lookback: the caller-supplied horizons that produced
        `upcoming_schedule_groups`/`recent_release_groups` --
        verbatim, never a hidden default (FX-54 Section 4/15: this
        story invents no fixed 15/30/60-minute policy window of
        its own).
    upcoming_schedule_groups: pair-relevant, PIT-visible forward-
        schedule evidence within `[as_of, as_of + lookahead)`,
        grouped by release package and sorted chronologically (see
        `domain.event_schedule_evidence.group_schedule_evidence`).
        An empty tuple means exactly "no PIT-visible, pair-relevant
        schedule evidence in this window among currently tracked
        indicators" -- see `coverage` for why that is not "safe."
    recent_release_groups: pair-relevant, PIT-visible release-
        occurrence evidence within `[as_of - lookback, as_of)`,
        grouped and sorted identically (see `domain.
        event_release_evidence.group_release_evidence`). Same
        "empty is not safe" caveat applies.
    coverage: structural coverage limitations for this pair (FX-54
        Section 19/21) -- always present, even when both evidence
        tuples are empty.
    """

    instrument: Instrument
    as_of: UtcTimestamp
    lookahead: timedelta
    lookback: timedelta
    upcoming_schedule_groups: tuple[EventEvidenceGroup[EventScheduleEvidence], ...]
    recent_release_groups: tuple[EventEvidenceGroup[EventReleaseEvidence], ...]
    coverage: EventCoverageEvidence

    def __post_init__(self) -> None:
        if self.lookahead < timedelta(0):
            raise ValueError(f"lookahead must not be negative, got {self.lookahead}")
        if self.lookback < timedelta(0):
            raise ValueError(f"lookback must not be negative, got {self.lookback}")
