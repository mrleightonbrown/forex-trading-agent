"""FX-52A: ingest official-source release-occurrence observations into
the FX-51H model, idempotently. Occurrence identity/correlation
hardened by FX-52AH.

Populates `EconomicEventReleaseVintage` ONLY -- never
`EconomicEventActualValueVintage`, even when the underlying source
payload happens to carry a numeric value (FX-52A Section 24; that
remains FX-52's own eventual scope). A release is recorded only from
POSITIVE source evidence (an official press-release/announcement feed
item) -- the mere passing of a previously-scheduled time is never
treated as evidence an event occurred (FX-52A Section 23).

Some adopted sources (the Federal Reserve's and Bank of England's
monetary-policy press-release feeds) have NO matching forward-schedule
source in this story at all (FX-52A Section 36's own documented gap) --
this use case must therefore be able to CREATE an occurrence lazily,
the first time release evidence for it arrives, exactly as a schedule
observation would. FX-52A Section 15 is explicit that this represents
"the first schedule/release state THIS SYSTEM has observed," never a
claim about the official source's own historical first publication.

Occurrence resolution, in order (FX-52AH):

1. If `(source, external_event_id, indicator_key)` already has a
   recorded mapping (`EconomicEventSourceMappingRepository`), use it
   directly -- no correlation needed on repeat polls of a source item
   already resolved once.
2. Otherwise, this is the FIRST time this exact external identity has
   been seen. Search existing occurrences of the same canonical
   indicator for ones whose latest known schedule places them on the
   SAME calendar date as this release evidence -- a deliberate,
   documented RECONCILIATION heuristic (date-match, not a guess at
   content), motivated by Bank of Canada's own case: its iCalendar
   schedule feed and RSS press-release feed use two completely
   independent external IDs for the same real announcement.
   - Exactly ONE candidate: correlate -- persist a mapping from this
     triple onto that candidate's `occurrence_key`, so every SUBSEQUENT
     poll of this exact triple resolves via step 1 and never repeats
     this heuristic (Section: "persist a successful correlation so
     future polls no longer depend on the heuristic").
   - ZERO candidates: no schedule to reconcile against (true for any
     source with release evidence but no adopted schedule feed at
     all) -- mint a genuinely new occurrence and record the mapping.
   - MORE THAN ONE candidate: ambiguous. Never silently choose among
     them -- report `AMBIGUOUS_CORRELATION` and do NOT create an
     occurrence, record a mapping, or write a release vintage for this
     indicator this poll. A future poll (once the ambiguity resolves
     itself, e.g. because only one candidate's own schedule still
     matches) may succeed where this one did not.
"""

from dataclasses import dataclass
from enum import Enum

from forex_agent.application.ports.economic_calendar_source import RawReleaseObservation
from forex_agent.application.ports.economic_event_repository import EconomicEventRepository
from forex_agent.application.ports.economic_event_source_mapping_repository import (
    EconomicEventSourceMappingRepository,
)
from forex_agent.domain.availability_confidence import AvailabilityConfidence
from forex_agent.domain.economic_calendar_occurrence_identity import mint_occurrence_key
from forex_agent.domain.economic_event_occurrence import EconomicEventOccurrence
from forex_agent.domain.economic_event_release_vintage import EconomicEventReleaseVintage
from forex_agent.domain.economic_event_schedule_vintage import EconomicEventScheduleVintage
from forex_agent.domain.economic_indicator_registry import indicator_by_key


class ReleaseIngestionDisposition(Enum):
    NEW_OCCURRENCE = "NEW_OCCURRENCE"
    CORRELATED = "CORRELATED"
    AMBIGUOUS_CORRELATION = "AMBIGUOUS_CORRELATION"
    NEW_RELEASE = "NEW_RELEASE"
    UNCHANGED = "UNCHANGED"
    CORRECTED = "CORRECTED"
    UNMAPPED = "UNMAPPED"


@dataclass(frozen=True, slots=True)
class ReleaseIngestionResult:
    occurrence_key: str
    indicator_key: str
    disposition: ReleaseIngestionDisposition


class IngestOfficialCalendarRelease:
    """FX-52A's release-occurrence ingestion use case -- see the module
    docstring."""

    def __init__(
        self,
        repository: EconomicEventRepository,
        mapping_repository: EconomicEventSourceMappingRepository,
    ) -> None:
        self._repository = repository
        self._mapping_repository = mapping_repository

    async def __call__(
        self, observations: tuple[RawReleaseObservation, ...]
    ) -> tuple[ReleaseIngestionResult, ...]:
        results: list[ReleaseIngestionResult] = []
        for observation in observations:
            for indicator_key in observation.indicator_keys:
                results.append(await self._ingest_one(indicator_key, observation))
        return tuple(results)

    async def _ingest_one(
        self, indicator_key: str, observation: RawReleaseObservation
    ) -> ReleaseIngestionResult:
        definition = indicator_by_key(indicator_key)
        if definition is None:
            return ReleaseIngestionResult(
                occurrence_key="",
                indicator_key=indicator_key,
                disposition=ReleaseIngestionDisposition.UNMAPPED,
            )

        resolution = await self._resolve_occurrence_key(indicator_key, observation)
        if resolution is None:
            return ReleaseIngestionResult(
                occurrence_key="",
                indicator_key=indicator_key,
                disposition=ReleaseIngestionDisposition.AMBIGUOUS_CORRELATION,
            )
        occurrence_key, resolution_disposition = resolution

        vintage_disposition = await self._ingest_release_vintage(occurrence_key, observation)
        disposition = resolution_disposition or vintage_disposition
        return ReleaseIngestionResult(
            occurrence_key=occurrence_key, indicator_key=indicator_key, disposition=disposition
        )

    async def _resolve_occurrence_key(
        self, indicator_key: str, observation: RawReleaseObservation
    ) -> tuple[str, ReleaseIngestionDisposition | None] | None:
        """`None` means AMBIGUOUS_CORRELATION -- the caller must not
        proceed any further for this indicator this poll. Otherwise
        `(occurrence_key, disposition_or_none)`: a non-`None`
        disposition means occurrence resolution ITSELF is the
        newsworthy event this poll (`NEW_OCCURRENCE`/`CORRELATED`);
        `None` means resolution used an already-recorded mapping and
        the eventual disposition should come from the vintage-write
        comparison instead."""
        existing = await self._mapping_repository.get_occurrence_key(
            observation.source, observation.external_event_id, indicator_key
        )
        if existing is not None:
            return existing, None

        candidates = await self._repository.list_occurrences_for_indicator(indicator_key)
        matches: list[str] = []
        for candidate in candidates:
            schedule_vintages = await self._repository.list_all_schedule_vintages(
                candidate.occurrence_key
            )
            latest_schedule = _latest_schedule_by_revision(schedule_vintages)
            if latest_schedule is not None and (
                latest_schedule.scheduled_date == observation.released_date
            ):
                matches.append(candidate.occurrence_key)

        if len(matches) > 1:
            return None
        if len(matches) == 1:
            occurrence_key = matches[0]
            await self._mapping_repository.record_mapping(
                observation.source, observation.external_event_id, indicator_key, occurrence_key
            )
            return occurrence_key, ReleaseIngestionDisposition.CORRELATED

        occurrence_key = mint_occurrence_key(indicator_key)
        await self._repository.add_occurrence(
            EconomicEventOccurrence(
                occurrence_key=occurrence_key,
                indicator_key=indicator_key,
                reference_period=None,
                release_group_key=None,
            )
        )
        await self._mapping_repository.record_mapping(
            observation.source, observation.external_event_id, indicator_key, occurrence_key
        )
        return occurrence_key, ReleaseIngestionDisposition.NEW_OCCURRENCE

    async def _ingest_release_vintage(
        self, occurrence_key: str, observation: RawReleaseObservation
    ) -> ReleaseIngestionDisposition:
        existing_vintages = await self._repository.list_all_release_vintages(occurrence_key)
        latest = _latest_release_by_revision(existing_vintages)

        if latest is not None and _same_release_fact(latest, observation):
            return ReleaseIngestionDisposition.UNCHANGED

        next_revision = 0 if latest is None else latest.revision_sequence + 1
        await self._repository.add_release_vintage(
            EconomicEventReleaseVintage(
                occurrence_key=occurrence_key,
                revision_sequence=next_revision,
                released_date=observation.released_date,
                released_time=observation.released_time,
                released_timezone=observation.released_timezone,
                availability=observation.observed_at,
                availability_confidence=AvailabilityConfidence.ESTIMATED,
                source=f"{observation.source}:{observation.external_event_id}",
                source_published_at=observation.source_published_at,
            )
        )
        return (
            ReleaseIngestionDisposition.NEW_RELEASE
            if latest is None
            else (ReleaseIngestionDisposition.CORRECTED)
        )


def _latest_schedule_by_revision(
    vintages: tuple[EconomicEventScheduleVintage, ...],
) -> EconomicEventScheduleVintage | None:
    if not vintages:
        return None
    return max(vintages, key=lambda v: v.revision_sequence)


def _latest_release_by_revision(
    vintages: tuple[EconomicEventReleaseVintage, ...],
) -> EconomicEventReleaseVintage | None:
    if not vintages:
        return None
    return max(vintages, key=lambda v: v.revision_sequence)


def _same_release_fact(
    latest: EconomicEventReleaseVintage, observation: RawReleaseObservation
) -> bool:
    # Deliberately excludes source_published_at: it is provenance about
    # WHEN the source said it published this evidence, not part of the
    # release fact itself (released_date/released_time/
    # released_timezone), so a poll that repeats the identical release
    # fact but observes a marginally different source_published_at
    # (e.g. a feed's own dc:date drifting by seconds between fetches)
    # must not be treated as a correction (FX-52AH.1).
    return (
        latest.released_date == observation.released_date
        and latest.released_time == observation.released_time
        and latest.released_timezone == observation.released_timezone
    )
