"""Ports for official-calendar source adapters (FX-52A; observability
and fail-closed semantics hardened by FX-52AH).

`RawScheduleObservation`/`RawReleaseObservation` are the normalized,
provider-neutral intermediate shape every source adapter (ICS/RSS/JSON)
must produce -- keeping source-specific parsing (`infrastructure.
economic_calendar_sources`), canonical mapping, and repository
persistence as separate responsibilities (FX-52A Section 30). Neither
carries a numeric value of any kind: FX-52A ingests TIMING only (see
each type's own docstring for why).

FX-52AH: `occurrence_key` is no longer derived from `(source,
external_event_id, indicator_key)` by these observations themselves --
see `domain.economic_calendar_occurrence_identity`'s own module
docstring. `fetch_schedule`/`fetch_releases` now return a result object
carrying `mapped_count`/`unmapped_count`/`invalid_count` alongside the
observations themselves (FX-52AH's own observability requirement: a
caller must never be left with zero visibility into how many raw
records were skipped and why).
"""

from dataclasses import dataclass
from datetime import date, time
from typing import Protocol

from forex_agent.domain.economic_event_status import EconomicEventStatus
from forex_agent.domain.timestamps import UtcTimestamp


class EconomicCalendarSourceUnavailableError(Exception):
    """Raised by a source adapter on a genuine network/parse failure --
    mirrors `PolicyRateProviderUnavailableError` (FX-43). A temporary
    outage, or a response that is not a recognizable document for this
    source's own format at all (FX-52AH -- see `ics_parsing.
    MalformedIcsError`/`rss_parsing.MalformedFeedError`), must surface
    as this, never as an empty, successful result (FX-52A Section 34):
    a caller receiving a result with zero observations must be able to
    trust that as "the source genuinely reports nothing new," not "the
    source was unreachable or returned garbage.\""""


@dataclass(frozen=True, slots=True)
class RawScheduleObservation:
    """One official source's claim, as observed at `observed_at`, that
    an event is scheduled for `scheduled_date`[/`scheduled_time`].

    `indicator_keys` is a tuple, not a single key, because one source
    item may identify more than one canonical indicator at once (a
    release package -- FX-52A Section 11); every entry maps onto its
    OWN `EconomicEventOccurrence` sharing one `release_group_key`, via
    `domain.economic_calendar_occurrence_identity.build_release_group_
    key`.

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
            canonical occurrence identity itself (FX-52AH); only used,
            together with `indicator_key`, as the lookup/record key
            into `EconomicEventSourceMappingRepository`.
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
        released_time: the local time of day, or `None` if the source
            does not establish an exact time with strong enough
            semantics -- never fabricated, and (FX-52AH) never
            populated merely because a feed item happens to carry SOME
            timestamp; see `boc_release_source`'s own docstring for a
            concrete case where a source's timestamp is preserved as
            `source_published_at` instead of promoted to this field.
        released_timezone: an IANA timezone name.
        source_published_at: when the SOURCE ITSELF says this evidence
            was published/dated (e.g. an RSS `dc:date`), if the source
            supplies one -- a THIRD, genuinely distinct instant from
            both `observed_at` (when THIS adapter retrieved it) and
            `released_date`/`released_time` (the claimed occurrence
            instant, if established with strong enough semantics).
            Preserved as provenance only; never interpreted by domain
            logic and never itself treated as `released_time` merely
            because it exists (FX-52AH).
    """

    source: str
    external_event_id: str
    indicator_keys: tuple[str, ...]
    released_date: date
    released_time: time | None
    released_timezone: str
    observed_at: UtcTimestamp
    raw_title: str
    source_published_at: UtcTimestamp | None = None


@dataclass(frozen=True, slots=True)
class ScheduleFetchResult:
    """`fetch_schedule`'s own result, with observable dispositions
    (FX-52AH) -- `mapped_count` is the number of source items that
    resolved to at least one canonical indicator (NOT the number of
    observations, since one release-package item can yield more than
    one); `unmapped_count` is source items that parsed fine but matched
    no canonical mapping; `invalid_count` is raw entries the underlying
    parser itself could not use at all (missing required fields, an
    unresolvable timezone, ...), passed through from `IcsParseResult`/
    `RssParseResult`."""

    observations: tuple[RawScheduleObservation, ...]
    mapped_count: int
    unmapped_count: int
    invalid_count: int


@dataclass(frozen=True, slots=True)
class ReleaseFetchResult:
    """`fetch_releases`' own result -- see `ScheduleFetchResult` for
    what each count means."""

    observations: tuple[RawReleaseObservation, ...]
    mapped_count: int
    unmapped_count: int
    invalid_count: int


class EconomicCalendarScheduleSource(Protocol):
    """One official source of forward-looking schedule timing."""

    async def fetch_schedule(self) -> ScheduleFetchResult:
        """Every schedule observation this source currently reports,
        already resolved to known canonical indicator(s), plus
        mapped/unmapped/invalid counts (FX-52AH). Raises
        `EconomicCalendarSourceUnavailableError` on a genuine source/
        network failure OR a malformed (not-this-format-at-all)
        response -- a temporary outage or garbage response must never
        be reported as an empty, successful result, since a caller
        could mistake that for "nothing is scheduled.\""""
        ...


class EconomicCalendarReleaseSource(Protocol):
    """One official source of positive release-occurrence evidence."""

    async def fetch_releases(self) -> ReleaseFetchResult:
        """Every release observation this source currently reports,
        already resolved to known canonical indicator(s), plus
        mapped/unmapped/invalid counts. Same UNMAPPED and outage-vs-
        malformed-vs-empty-result discipline as
        `EconomicCalendarScheduleSource.fetch_schedule`."""
        ...
