"""FX-52A: ingest official-source release-occurrence observations into
the FX-51H model, idempotently.

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

Occurrence correlation: when a source's OWN release-evidence feed uses
a different external identifier from that same event's schedule-source
feed (true of Bank of Canada, whose iCalendar schedule and press-
release RSS are two independent feeds with two independent IDs for the
same real announcement), this use case looks for an EXISTING occurrence
of the same canonical indicator whose latest known schedule places it
on the SAME calendar date as the release evidence, and attaches the
release vintage there instead of minting a second, duplicate
occurrence. This is a deliberate, documented heuristic (date-match, not
a guess at content) -- see the module's own test coverage for its
exact boundary; a future story with better cross-source identity could
replace it without changing this use case's own public contract.
"""

from dataclasses import dataclass
from enum import Enum

from forex_agent.application.ports.economic_calendar_source import RawReleaseObservation
from forex_agent.application.ports.economic_event_repository import EconomicEventRepository
from forex_agent.domain.availability_confidence import AvailabilityConfidence
from forex_agent.domain.economic_calendar_occurrence_identity import build_occurrence_key
from forex_agent.domain.economic_event_occurrence import EconomicEventOccurrence
from forex_agent.domain.economic_event_release_vintage import EconomicEventReleaseVintage
from forex_agent.domain.economic_event_schedule_vintage import EconomicEventScheduleVintage
from forex_agent.domain.economic_indicator_registry import indicator_by_key


class ReleaseIngestionDisposition(Enum):
    NEW_OCCURRENCE = "NEW_OCCURRENCE"
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

    def __init__(self, repository: EconomicEventRepository) -> None:
        self._repository = repository

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

        occurrence_key = await self._resolve_occurrence_key(indicator_key, observation)
        is_new_occurrence = await self._repository.get_occurrence(occurrence_key) is None
        if is_new_occurrence:
            await self._repository.add_occurrence(
                EconomicEventOccurrence(
                    occurrence_key=occurrence_key,
                    indicator_key=indicator_key,
                    reference_period=None,
                    release_group_key=None,
                )
            )

        existing_vintages = await self._repository.list_all_release_vintages(occurrence_key)
        latest = _latest_release_by_revision(existing_vintages)

        if latest is not None and _same_release_fact(latest, observation):
            disposition = ReleaseIngestionDisposition.UNCHANGED
        else:
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
                )
            )
            disposition = (
                ReleaseIngestionDisposition.NEW_OCCURRENCE
                if is_new_occurrence
                else (
                    ReleaseIngestionDisposition.NEW_RELEASE
                    if latest is None
                    else ReleaseIngestionDisposition.CORRECTED
                )
            )
        return ReleaseIngestionResult(
            occurrence_key=occurrence_key, indicator_key=indicator_key, disposition=disposition
        )

    async def _resolve_occurrence_key(
        self, indicator_key: str, observation: RawReleaseObservation
    ) -> str:
        candidates = await self._repository.list_occurrences_for_indicator(indicator_key)
        for candidate in candidates:
            schedule_vintages = await self._repository.list_all_schedule_vintages(
                candidate.occurrence_key
            )
            latest_schedule = _latest_schedule_by_revision(schedule_vintages)
            if latest_schedule is not None and (
                latest_schedule.scheduled_date == observation.released_date
            ):
                return candidate.occurrence_key
        return build_occurrence_key(
            observation.source, observation.external_event_id, indicator_key
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
    return (
        latest.released_date == observation.released_date
        and latest.released_time == observation.released_time
        and latest.released_timezone == observation.released_timezone
    )
