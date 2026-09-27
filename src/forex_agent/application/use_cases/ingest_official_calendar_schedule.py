"""FX-52A: ingest official-source schedule observations into the FX-51/
FX-51H model, idempotently. Occurrence identity hardened by FX-52AH.

This use case does no PIT logic of its own beyond change-detection: it
asks the repository what the latest known schedule vintage for an
occurrence is, compares it field-by-field against the newly observed
fact, and only writes a new vintage when something genuinely differs
-- repeated identical polls must never create duplicate vintages
(FX-52A Section 16), and `EconomicEventVintageConflictError` would
reject an exact-duplicate-content write attempt anyway (belt and
braces, not the primary mechanism).

Occurrence identity: a schedule source is the AUTHORITATIVE claimant
for its own `(source, external_event_id, indicator_key)` triple -- no
cross-feed correlation happens here (that is `IngestOfficialCalendar
Release`'s own job, for release evidence arriving from a possibly
DIFFERENT feed). The first time this exact triple is seen, a fresh,
provider-neutral `occurrence_key` is minted (`domain.economic_
calendar_occurrence_identity.mint_occurrence_key`) and the mapping is
recorded; every subsequent poll of the SAME triple resolves to the
SAME `occurrence_key` via the persisted mapping repository, never by
recomputing anything from `source`/`external_event_id`.

Cancellation/postponement are represented exactly as `RawSchedule
Observation.status` claims -- never inferred from an item's absence
from the current fetch (FX-52A Section 18): this use case only ever
processes observations it was actually GIVEN; an occurrence whose
latest source item simply was not present in this poll is left
completely untouched, which is the correct behaviour by construction,
not a special case handled here.
"""

from dataclasses import dataclass
from enum import Enum

from forex_agent.application.ports.economic_calendar_source import RawScheduleObservation
from forex_agent.application.ports.economic_event_repository import EconomicEventRepository
from forex_agent.application.ports.economic_event_source_mapping_repository import (
    EconomicEventSourceMappingRepository,
)
from forex_agent.domain.availability_confidence import AvailabilityConfidence
from forex_agent.domain.economic_calendar_occurrence_identity import (
    build_release_group_key,
    mint_occurrence_key,
)
from forex_agent.domain.economic_event_occurrence import EconomicEventOccurrence
from forex_agent.domain.economic_event_schedule_vintage import EconomicEventScheduleVintage
from forex_agent.domain.economic_event_status import EconomicEventStatus
from forex_agent.domain.economic_indicator_registry import indicator_by_key


class ScheduleIngestionDisposition(Enum):
    """What happened to one `RawScheduleObservation`, for exactly one
    of its `indicator_keys` (FX-52A Section 16/36)."""

    NEW_OCCURRENCE = "NEW_OCCURRENCE"
    NEW_SCHEDULE = "NEW_SCHEDULE"
    UNCHANGED = "UNCHANGED"
    RESCHEDULED = "RESCHEDULED"
    POSTPONED = "POSTPONED"
    CANCELLED = "CANCELLED"
    REINSTATED = "REINSTATED"
    UNMAPPED = "UNMAPPED"


@dataclass(frozen=True, slots=True)
class ScheduleIngestionResult:
    occurrence_key: str
    indicator_key: str
    disposition: ScheduleIngestionDisposition


class IngestOfficialCalendarSchedule:
    """FX-52A's forward-schedule ingestion use case -- see the module
    docstring."""

    def __init__(
        self,
        repository: EconomicEventRepository,
        mapping_repository: EconomicEventSourceMappingRepository,
    ) -> None:
        self._repository = repository
        self._mapping_repository = mapping_repository

    async def __call__(
        self, observations: tuple[RawScheduleObservation, ...]
    ) -> tuple[ScheduleIngestionResult, ...]:
        results: list[ScheduleIngestionResult] = []
        for observation in observations:
            results.extend(await self._ingest_one(observation))
        return tuple(results)

    async def _ingest_one(
        self, observation: RawScheduleObservation
    ) -> tuple[ScheduleIngestionResult, ...]:
        release_group_key = (
            build_release_group_key(observation.source, observation.external_event_id)
            if len(observation.indicator_keys) > 1
            else None
        )
        results: list[ScheduleIngestionResult] = []
        for indicator_key in observation.indicator_keys:
            definition = indicator_by_key(indicator_key)
            if definition is None:
                results.append(
                    ScheduleIngestionResult(
                        occurrence_key="",
                        indicator_key=indicator_key,
                        disposition=ScheduleIngestionDisposition.UNMAPPED,
                    )
                )
                continue
            occurrence_key, is_new_occurrence = await self._resolve_occurrence_key(
                indicator_key, release_group_key, observation
            )
            disposition = await self._ingest_indicator(
                occurrence_key, is_new_occurrence, observation
            )
            results.append(
                ScheduleIngestionResult(
                    occurrence_key=occurrence_key,
                    indicator_key=indicator_key,
                    disposition=disposition,
                )
            )
        return tuple(results)

    async def _resolve_occurrence_key(
        self,
        indicator_key: str,
        release_group_key: str | None,
        observation: RawScheduleObservation,
    ) -> tuple[str, bool]:
        existing = await self._mapping_repository.get_occurrence_key(
            observation.source, observation.external_event_id, indicator_key
        )
        if existing is not None:
            if release_group_key is not None:
                existing_occurrence = await self._repository.get_occurrence(existing)
                already_grouped = (
                    existing_occurrence is not None
                    and existing_occurrence.release_group_key is not None
                )
                if existing_occurrence is not None and not already_grouped:
                    await self._repository.attach_release_group(existing, release_group_key)
            return existing, False

        occurrence_key = mint_occurrence_key(indicator_key)
        await self._repository.add_occurrence(
            EconomicEventOccurrence(
                occurrence_key=occurrence_key,
                indicator_key=indicator_key,
                reference_period=observation.reference_period,
                release_group_key=release_group_key,
            )
        )
        await self._mapping_repository.record_mapping(
            observation.source, observation.external_event_id, indicator_key, occurrence_key
        )
        return occurrence_key, True

    async def _ingest_indicator(
        self,
        occurrence_key: str,
        is_new_occurrence: bool,
        observation: RawScheduleObservation,
    ) -> ScheduleIngestionDisposition:
        existing_vintages = await self._repository.list_all_schedule_vintages(occurrence_key)
        latest = _latest_by_revision(existing_vintages)

        if latest is not None and _same_schedule_fact(latest, observation):
            return ScheduleIngestionDisposition.UNCHANGED

        next_revision = 0 if latest is None else latest.revision_sequence + 1
        await self._repository.add_schedule_vintage(
            EconomicEventScheduleVintage(
                occurrence_key=occurrence_key,
                revision_sequence=next_revision,
                scheduled_date=observation.scheduled_date,
                scheduled_time=observation.scheduled_time,
                schedule_timezone=observation.schedule_timezone,
                status=observation.status,
                availability=observation.observed_at,
                availability_confidence=AvailabilityConfidence.ESTIMATED,
                source=f"{observation.source}:{observation.external_event_id}",
            )
        )

        if latest is None:
            return (
                ScheduleIngestionDisposition.NEW_OCCURRENCE
                if is_new_occurrence
                else ScheduleIngestionDisposition.NEW_SCHEDULE
            )
        return _transition_disposition(latest.status, observation.status)


def _latest_by_revision(
    vintages: tuple[EconomicEventScheduleVintage, ...],
) -> EconomicEventScheduleVintage | None:
    if not vintages:
        return None
    return max(vintages, key=lambda v: v.revision_sequence)


def _same_schedule_fact(
    latest: EconomicEventScheduleVintage, observation: RawScheduleObservation
) -> bool:
    return (
        latest.scheduled_date == observation.scheduled_date
        and latest.scheduled_time == observation.scheduled_time
        and latest.schedule_timezone == observation.schedule_timezone
        and latest.status == observation.status
    )


def _transition_disposition(
    previous_status: EconomicEventStatus,
    new_status: EconomicEventStatus,
) -> ScheduleIngestionDisposition:
    if new_status is EconomicEventStatus.CANCELLED and previous_status is not (
        EconomicEventStatus.CANCELLED
    ):
        return ScheduleIngestionDisposition.CANCELLED
    if new_status is EconomicEventStatus.POSTPONED and previous_status is not (
        EconomicEventStatus.POSTPONED
    ):
        return ScheduleIngestionDisposition.POSTPONED
    if new_status is EconomicEventStatus.SCHEDULED and previous_status in (
        EconomicEventStatus.POSTPONED,
        EconomicEventStatus.CANCELLED,
    ):
        return ScheduleIngestionDisposition.REINSTATED
    return ScheduleIngestionDisposition.RESCHEDULED
