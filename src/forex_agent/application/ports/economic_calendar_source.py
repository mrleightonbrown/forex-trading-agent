"""Ports for official-calendar source adapters (FX-52A).

`RawScheduleObservation`/`RawReleaseObservation` are the normalized,
provider-neutral intermediate shape every source adapter (ICS/RSS/JSON)
must produce -- keeping source-specific parsing (`infrastructure.
economic_calendar_sources`), canonical mapping, and repository
persistence as separate responsibilities (FX-52A Section 30). Neither
carries a numeric value of any kind: FX-52A ingests TIMING only (see
each type's own docstring for why).
"""

from dataclasses import dataclass
from datetime import date, time
from typing import Protocol

from forex_agent.domain.economic_event_status import EconomicEventStatus
from forex_agent.domain.timestamps import UtcTimestamp


class EconomicCalendarSourceUnavailableError(Exception):
    """Raised by a source adapter on a genuine network/parse failure --
    mirrors `PolicyRateProviderUnavailableError` (FX-43). A temporary
    outage must surface as this, never as an empty, successful result
    (FX-52A Section 34): a caller receiving `()` from `fetch_schedule`/
    `fetch_releases` must be able to trust that as "the source
    genuinely reports nothing new," not "the source was unreachable.\""""


@dataclass(frozen=True, slots=True)
class RawScheduleObservation:
    """One official source's claim, as observed at `observed_at`, that
    an event is scheduled for `scheduled_date`[/`scheduled_time`].

    `indicator_keys` is a tuple, not a single key, because one source
    item may identify more than one canonical indicator at once (a
    release package -- FX-52A Section 11); every entry maps onto its
    OWN `EconomicEventOccurrence` sharing one `release_group_key`, via
    `domain.economic_calendar_occurrence_identity`.

    `observed_at` is when THIS adapter retrieved this exact fact, not
    when the official source itself first published the schedule --
    FX-52A is prospective-collection-only (Section 5): this project has
    no way to know when the government first published a schedule that
    has been on a public calendar for months, so `observed_at` is the
    only defensible availability anchor, and it is `ESTIMATED`
    confidence unless a source separately supplies a stronger
    publication timestamp (none of FX-52A's adopted sources do).

    Fields:
        source: a short, stable label identifying the adapter/feed this
            observation came from (e.g. "BLS_ICS", "ONS_RSS",
            "BOC_ICS") -- never a full URL, never user-facing.
        external_event_id: the source's own stable identifier for this
            calendar item (an ICS UID, an RSS guid, ...) -- never
            treated as canonical occurrence identity itself; only used,
            together with `source` and each indicator key, to DERIVE
            one via `domain.economic_calendar_occurrence_identity.
            build_occurrence_key`.
        indicator_keys: which canonical `EconomicIndicatorDefinition`
            key(s) this item maps to (already resolved -- an adapter
            that cannot confidently map an item must not construct one
            of these at all; see each adapter's own UNMAPPED handling).
        scheduled_date: the calendar date the source claims, in
            `schedule_timezone`'s local civil time.
        scheduled_time: the local time of day, or `None` if the source
            only established a date -- never fabricated.
        schedule_timezone: an IANA timezone name.
        status: the source's claimed lifecycle status (see
            `EconomicEventStatus`) -- `SCHEDULED` unless the source
            gives POSITIVE evidence of `POSTPONED`/`CANCELLED`
            (FX-52A Section 18); absence from a feed is never evidence
            of either, and an adapter must simply not emit an
            observation at all for an item it does not see, rather
            than emit one claiming cancellation.
        observed_at: when this adapter retrieved this exact fact.
        raw_title: the source's own unmodified event title/summary --
            provenance only, never interpreted by domain logic.
        reference_period: the occurrence's reference period, ONLY when
            the source's own content explicitly establishes it (e.g. a
            title stating "April to June 2026") -- never derived by an
            adapter's own arithmetic assumption (FX-52A Section 14).
            `None` is the correct, default value; only used the first
            time an occurrence is created, since it is a one-time
            occurrence-level fact, not a vintaged one.
    """

    source: str
    external_event_id: str
    indicator_keys: tuple[str, ...]
    scheduled_date: date
    scheduled_time: time | None
    schedule_timezone: str
    status: EconomicEventStatus
    observed_at: UtcTimestamp
    raw_title: str
    reference_period: UtcTimestamp | None = None


@dataclass(frozen=True, slots=True)
class RawReleaseObservation:
    """One official source's positive evidence that an event actually
    occurred/was released on `released_date`[/`released_time`].

    Deliberately carries NO numeric value field of any kind, even when
    the underlying source payload contains one (FX-52A Section 24) --
    only this project's `EconomicEventReleaseVintage` shape (released
    date/time + availability), never an actual-value fact. `released_
    date`/`released_time` are the source's own claimed release
    instant, kept explicitly independent of `observed_at` (when this
    adapter itself saw that evidence) -- FX-52A Section 23/29's own
    central distinction, mirroring `EconomicEventReleaseVintage`'s own
    docstring.

    Fields: see `RawScheduleObservation` for the shared ones
    (`source`, `external_event_id`, `indicator_keys`, `observed_at`,
    `raw_title`).
        released_date: the calendar date the source's own evidence
            claims the event actually occurred/released on.
        released_time: the local time of day, or `None` if only a date
            is evidenced -- never fabricated.
        released_timezone: an IANA timezone name.
    """

    source: str
    external_event_id: str
    indicator_keys: tuple[str, ...]
    released_date: date
    released_time: time | None
    released_timezone: str
    observed_at: UtcTimestamp
    raw_title: str


class EconomicCalendarScheduleSource(Protocol):
    """One official source of forward-looking schedule timing."""

    async def fetch_schedule(self) -> tuple[RawScheduleObservation, ...]:
        """Every schedule observation this source currently reports,
        already resolved to known canonical indicator(s) -- an item
        this adapter cannot confidently map is simply omitted (report
        UNMAPPED separately; never guess). Raises on a genuine
        source/network failure (see each adapter's own docstring for
        which exceptions) -- a temporary outage must never be reported
        as an empty, successful result, since a caller could mistake
        that for "nothing is scheduled.\""""
        ...


class EconomicCalendarReleaseSource(Protocol):
    """One official source of positive release-occurrence evidence."""

    async def fetch_releases(self) -> tuple[RawReleaseObservation, ...]:
        """Every release observation this source currently reports,
        already resolved to known canonical indicator(s). Same
        UNMAPPED and outage-vs-empty-result discipline as
        `EconomicCalendarScheduleSource.fetch_schedule`."""
        ...
