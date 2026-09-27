from dataclasses import dataclass
from datetime import date, time
from zoneinfo import ZoneInfo

from forex_agent.domain._guards import require_availability_consistency, require_revision_sequence
from forex_agent.domain.availability_confidence import AvailabilityConfidence
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class EconomicEventReleaseVintage:
    """One point-in-time-safe fact: "occurrence X was known, from
    `availability` onward, to have ACTUALLY occurred/been released on
    `released_date`[/`released_time`]" (FX-51H Section 1/2).

    This is the provider-neutral, general "this occurrence happened"
    fact -- deliberately distinct from `EconomicEventActualValueVintage`,
    which additionally carries a NUMBER. FX-51's original model could
    only represent "an occurrence happened" implicitly, by the mere
    existence of an actual-value vintage -- which left no honest way to
    record that a QUALITATIVE event (a central-bank press conference, a
    set of meeting minutes, an unscheduled statement) actually took
    place, since such an event has no number to invent one for. This
    type fixes that: any occurrence, numeric or not, gets a release
    vintage once it is known to have occurred; a numeric occurrence
    ADDITIONALLY gets an `EconomicEventActualValueVintage` for its own
    value. Neither type infers the other -- a caller must record both
    facts separately when both exist.

    Also fixes a subtler conflation FX-51's original model left
    implicit: "when the event was released" (`released_date`/
    `released_time`) and "when the system could first have known that"
    (`availability`) are two independent instants, exactly the same
    distinction `EconomicEventScheduleVintage` already draws between a
    schedule's own claimed date/time and its own `availability`. A
    same-day statement whose transcript is only published two days
    later has `released_date` on the statement's own day and
    `availability` two days after it -- collapsing the two would let a
    PIT query "see" the release before the system could actually have
    known about it.

    Same immutable-fact-per-row shape as every other FX-51 vintage
    type: a correction (e.g. a revised release timestamp once a more
    authoritative source is found) is a NEW vintage with a later
    `availability` and a higher `revision_sequence`, never a mutation.

    `released_time` is `None` precisely when the source has only
    established a DATE, not a time -- mirrors
    `EconomicEventScheduleVintage.scheduled_time`'s own contract
    exactly, for the identical reason: never fabricate a time of day
    for a genuinely unknown one.

    Fields:
        occurrence_key: the `EconomicEventOccurrence.occurrence_key`
            this release vintage belongs to.
        revision_sequence: 0 for the first-known release fact of this
            occurrence, incrementing for each subsequent correction.
        released_date: the calendar date this vintage claims the
            occurrence actually released/occurred on, in
            `released_timezone`'s local civil time.
        released_time: the local time of day, in `released_timezone`,
            or `None` if only the date is known. Never fabricated --
            see the class docstring.
        released_timezone: an IANA timezone name giving `released_date`/
            `released_time` their local frame of reference, preserved
            even when `released_time` is `None`.
        availability: when this exact release fact became knowable to
            the system, or `None` if genuinely `UNKNOWN` (see
            `AvailabilityConfidence`) -- point-in-time queries filter
            against this, never against `released_date`/`released_time`
            or any database insertion timestamp.
        availability_confidence: how strongly `availability` is
            evidenced. Must be `AvailabilityConfidence.UNKNOWN` if and
            only if `availability` is `None`.
        source: free-form provenance label -- never branched on by
            domain logic.
        source_published_at: when the SOURCE ITSELF said this evidence
            was published/dated (e.g. an RSS `dc:date`), if the source
            supplied one -- FX-52AH.1: a genuinely durable, independent
            THIRD instant, distinct from both `availability` (when
            THIS system could first know the fact) and any database
            row-creation timestamp. Mirrors `RawReleaseObservation.
            source_published_at`'s own docstring exactly; this is where
            that value is actually persisted, since FX-52AH introduced
            the field on the port-layer observation but never carried
            it through into this vintage type or its own storage,
            leaving it computed and then silently discarded on every
            real poll. `None` when the source did not supply one, or
            never interpreted as `released_time` regardless (FX-52AH's
            own correction already established that a feed's generic
            publication timestamp must never be promoted to the
            claimed occurrence time without primary documentation
            establishing that equivalence).
    """

    occurrence_key: str
    revision_sequence: int
    released_date: date
    released_time: time | None
    released_timezone: str
    availability: UtcTimestamp | None
    availability_confidence: AvailabilityConfidence
    source: str
    source_published_at: UtcTimestamp | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.occurrence_key, str) or not self.occurrence_key.strip():
            raise ValueError(
                f"occurrence_key must be a non-empty string, got {self.occurrence_key!r}"
            )
        require_revision_sequence(self.revision_sequence)
        if not isinstance(self.released_date, date):
            raise TypeError(f"released_date must be a date, got {type(self.released_date)!r}")
        if self.released_time is not None and not isinstance(self.released_time, time):
            raise TypeError(
                f"released_time must be a time or None, got {type(self.released_time)!r}"
            )
        if not isinstance(self.released_timezone, str) or not self.released_timezone.strip():
            raise ValueError(
                f"released_timezone must be a non-empty string, got {self.released_timezone!r}"
            )
        ZoneInfo(self.released_timezone)  # raises ZoneInfoNotFoundError immediately for a bad name
        require_availability_consistency(self.availability, self.availability_confidence)
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError(f"source must be a non-empty string, got {self.source!r}")
        if self.source_published_at is not None and not isinstance(
            self.source_published_at, UtcTimestamp
        ):
            raise TypeError(
                "source_published_at must be a UtcTimestamp or None, got "
                f"{type(self.source_published_at).__name__}"
            )
