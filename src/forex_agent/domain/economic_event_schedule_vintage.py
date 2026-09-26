from dataclasses import dataclass
from datetime import date, time
from zoneinfo import ZoneInfo

from forex_agent.domain._guards import require_availability_consistency, require_revision_sequence
from forex_agent.domain.availability_confidence import AvailabilityConfidence
from forex_agent.domain.economic_event_status import EconomicEventStatus
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class EconomicEventScheduleVintage:
    """One point-in-time-safe fact: "occurrence X was known, from
    `availability` onward, to be scheduled for `scheduled_date`[/
    `scheduled_time`], with status `status`" (FX-51 Section 5.3).

    A reschedule, postponement, cancellation, or reinstatement is a NEW
    vintage with a later `availability` and a higher `revision_
    sequence` for the SAME `occurrence_key` -- never a mutation of an
    earlier vintage, and never a change to the occurrence's own
    identity (FX-51H Section 5): a reschedule is purely a new row in
    THIS vintage history. This is `MacroObservationVintage`'s own
    immutable-fact-per-row shape (FX-41), applied to scheduling instead
    of an economic value: there is no separate "initial schedule" type
    distinct from "a reschedule" the same way FX-41 deliberately has no
    separate "first release" type distinct from "a revision" -- both
    are simply the vintage with `revision_sequence == 0`.

    `scheduled_time` is `None` precisely when the source has only
    established a DATE, not a time -- FX-51 Section 11 is explicit:
    "an unknown release time is uncertainty, not a missing default."
    Nothing in this type may substitute midnight, market open, or any
    other fabricated time for a genuinely unknown one; a caller must
    check for `None` and represent that state explicitly rather than
    guess.

    Fields:
        occurrence_key: the `EconomicEventOccurrence.occurrence_key`
            this schedule vintage belongs to (FX-51H: identity moved
            off `(indicator_key, reference_period)` onto this single
            stable key -- see `EconomicEventOccurrence`'s own
            docstring).
        revision_sequence: 0 for the first-known schedule of this
            occurrence, incrementing for each subsequent change
            (reschedule, postponement, cancellation, reinstatement, or
            a source correction). Not required to be contiguous or
            provider-comparable -- only used to order this
            occurrence's own schedule vintages relative to each other.
        scheduled_date: the calendar date this vintage claims the event
            is scheduled for, in `schedule_timezone`'s local civil
            time.
        scheduled_time: the local time of day, in `schedule_timezone`,
            or `None` if only the date is known. See the class
            docstring -- never fabricated.
        schedule_timezone: an IANA timezone name (e.g.
            "America/New_York") giving `scheduled_date`/`scheduled_time`
            their local frame of reference, preserved even when
            `scheduled_time` is `None` (FX-51 Section 11: "preserve
            source/local timezone context when useful").
        status: this vintage's own lifecycle status (see
            `EconomicEventStatus`) -- what the schedule claims AS OF
            `availability`, not a permanent classification of the
            occurrence itself.
        availability: when this exact schedule fact became knowable to
            the system, or `None` if genuinely `UNKNOWN` (see
            `AvailabilityConfidence`) -- point-in-time queries filter
            against this, never against `scheduled_date`/
            `scheduled_time` or any database insertion timestamp.
        availability_confidence: how strongly `availability` is
            evidenced. Must be `AvailabilityConfidence.UNKNOWN` if and
            only if `availability` is `None` (enforced in
            `__post_init__`).
        source: free-form provenance label (e.g. a calendar vendor
            name, "manual_backfill") -- no provider-specific object,
            never branched on by domain logic (mirrors
            `MacroObservationVintage.source`).
    """

    occurrence_key: str
    revision_sequence: int
    scheduled_date: date
    scheduled_time: time | None
    schedule_timezone: str
    status: EconomicEventStatus
    availability: UtcTimestamp | None
    availability_confidence: AvailabilityConfidence
    source: str

    def __post_init__(self) -> None:
        if not isinstance(self.occurrence_key, str) or not self.occurrence_key.strip():
            raise ValueError(
                f"occurrence_key must be a non-empty string, got {self.occurrence_key!r}"
            )
        require_revision_sequence(self.revision_sequence)
        if not isinstance(self.scheduled_date, date):
            raise TypeError(f"scheduled_date must be a date, got {type(self.scheduled_date)!r}")
        if self.scheduled_time is not None and not isinstance(self.scheduled_time, time):
            raise TypeError(
                f"scheduled_time must be a time or None, got {type(self.scheduled_time)!r}"
            )
        if not isinstance(self.schedule_timezone, str) or not self.schedule_timezone.strip():
            raise ValueError(
                f"schedule_timezone must be a non-empty string, got {self.schedule_timezone!r}"
            )
        ZoneInfo(self.schedule_timezone)  # raises ZoneInfoNotFoundError immediately for a bad name
        if not isinstance(self.status, EconomicEventStatus):
            raise TypeError(f"status must be an EconomicEventStatus, got {type(self.status)!r}")
        require_availability_consistency(self.availability, self.availability_confidence)
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError(f"source must be a non-empty string, got {self.source!r}")
