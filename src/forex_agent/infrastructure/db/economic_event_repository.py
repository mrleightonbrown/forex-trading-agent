"""SQLAlchemy implementation of `EconomicEventRepository` (FX-51;
identity/release model hardened by FX-51H).

Enforces the point-in-time invariant ("a query at T cannot return a
vintage whose availability is None or after T") entirely through each
`*_as_of` method's own `WHERE availability <= :as_of` clause -- there is
deliberately no separate "safety check" layered on top; the SQL
predicate IS the safety guarantee, exactly as
`SqlAlchemyMacroObservationRepository` (FX-41) already established.
Every write is a plain `INSERT ... ON CONFLICT DO NOTHING` -- no method
in this class ever issues an UPDATE against a vintage table, so a
historical vintage row can never be mutated once stored. The ONE
exception is `attach_release_group`'s own narrowly-scoped, atomically-
conditional `UPDATE` against `economic_event_occurrences` -- legitimate
because `release_group_key` was never a vintaged, temporal fact (see
`domain.economic_event_occurrence.EconomicEventOccurrence`'s own
docstring), mirroring `SqlAlchemyMacroObservationRepository.
replace_provisional_release_timing`'s (FX-43H) identical discipline for
its own single legitimate mutation.

`known_events_in_window` resolves window membership through
`domain.economic_event_state.schedule_within_window` -- a true UTC-
instant (or, for a date-only/TBD schedule, a true UTC local-day range)
test, evaluated in Python after a SQL query that only ranks and
availability-filters. FX-51H Section 4 replaced FX-51's original SQL-
only date-range comparison, which compared a local calendar date
against `start`/`end`'s own UTC calendar dates and could place a
boundary-adjacent event on the wrong side of the window by a day.
"""

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from forex_agent.application.ports.economic_event_repository import (
    EconomicEventOccurrenceConflictError,
    EconomicEventVintageConflictError,
    VintageWriteOutcome,
)
from forex_agent.domain.availability_confidence import AvailabilityConfidence
from forex_agent.domain.economic_event_actual_value_vintage import (
    EconomicEventActualValueVintage,
)
from forex_agent.domain.economic_event_consensus_vintage import EconomicEventConsensusVintage
from forex_agent.domain.economic_event_occurrence import EconomicEventOccurrence
from forex_agent.domain.economic_event_release_vintage import EconomicEventReleaseVintage
from forex_agent.domain.economic_event_schedule_vintage import EconomicEventScheduleVintage
from forex_agent.domain.economic_event_state import schedule_within_window
from forex_agent.domain.economic_event_status import EconomicEventStatus
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.models.economic_event_actual_value_vintage import (
    EconomicEventActualValueVintageRow,
)
from forex_agent.infrastructure.db.models.economic_event_consensus_vintage import (
    EconomicEventConsensusVintageRow,
)
from forex_agent.infrastructure.db.models.economic_event_occurrence import (
    EconomicEventOccurrenceRow,
)
from forex_agent.infrastructure.db.models.economic_event_release_vintage import (
    EconomicEventReleaseVintageRow,
)
from forex_agent.infrastructure.db.models.economic_event_schedule_vintage import (
    EconomicEventScheduleVintageRow,
)

_VINTAGE_KEY = ("occurrence_key", "revision_sequence")


class SqlAlchemyEconomicEventRepository:
    """Implements `EconomicEventRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- Occurrences ---------------------------------------------------------

    async def add_occurrence(self, occurrence: EconomicEventOccurrence) -> VintageWriteOutcome:
        stmt = (
            pg_insert(EconomicEventOccurrenceRow)
            .values(
                occurrence_key=occurrence.occurrence_key,
                indicator_key=occurrence.indicator_key,
                reference_period=(
                    None
                    if occurrence.reference_period is None
                    else occurrence.reference_period.value
                ),
                release_group_key=occurrence.release_group_key,
            )
            .on_conflict_do_nothing(index_elements=["occurrence_key"])
            .returning(EconomicEventOccurrenceRow.id)
        )
        inserted_id = (await self._session.execute(stmt)).scalar_one_or_none()
        if inserted_id is not None:
            await self._session.commit()
            return VintageWriteOutcome.INSERTED

        existing = await self.get_occurrence(occurrence.occurrence_key)
        await self._session.commit()
        assert existing is not None  # the failed insert proves the identity already exists
        if existing == occurrence:
            return VintageWriteOutcome.ALREADY_PRESENT
        raise EconomicEventOccurrenceConflictError(existing, occurrence)

    async def get_occurrence(self, occurrence_key: str) -> EconomicEventOccurrence | None:
        stmt = select(EconomicEventOccurrenceRow).where(
            EconomicEventOccurrenceRow.occurrence_key == occurrence_key
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _occurrence_to_domain(row)

    async def list_occurrences_for_indicator(
        self, indicator_key: str
    ) -> tuple[EconomicEventOccurrence, ...]:
        stmt = select(EconomicEventOccurrenceRow).where(
            EconomicEventOccurrenceRow.indicator_key == indicator_key
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        await self._session.commit()
        return tuple(_occurrence_to_domain(row) for row in rows)

    async def attach_release_group(self, occurrence_key: str, release_group_key: str) -> None:
        # Same atomic-conditional-UPDATE-with-RETURNING discipline as
        # `SqlAlchemyMacroObservationRepository.replace_provisional_
        # release_timing` (FX-43H) -- `release_group_key IS NULL` is part
        # of the UPDATE's own WHERE clause, so the still-unattached check
        # and the write happen in one statement.
        stmt = (
            update(EconomicEventOccurrenceRow)
            .where(
                EconomicEventOccurrenceRow.occurrence_key == occurrence_key,
                EconomicEventOccurrenceRow.release_group_key.is_(None),
            )
            .values(release_group_key=release_group_key)
            .returning(EconomicEventOccurrenceRow.id)
        )
        updated_id = (await self._session.execute(stmt)).scalar_one_or_none()
        if updated_id is not None:
            await self._session.commit()
            return

        await self._session.commit()  # release the no-op transaction before re-reading
        existing = await self.get_occurrence(occurrence_key)
        if existing is None:
            raise ValueError(f"no occurrence exists at occurrence_key={occurrence_key!r}")
        if existing.release_group_key == release_group_key:
            return  # idempotent no-op: already attached to this exact group
        raise ValueError(
            f"occurrence_key={occurrence_key!r} already has release_group_key="
            f"{existing.release_group_key!r}, cannot attach a different "
            f"release_group_key={release_group_key!r}"
        )

    # --- Schedule vintages -----------------------------------------------------

    async def add_schedule_vintage(
        self, vintage: EconomicEventScheduleVintage
    ) -> VintageWriteOutcome:
        stmt = (
            pg_insert(EconomicEventScheduleVintageRow)
            .values(_schedule_row_values(vintage))
            .on_conflict_do_nothing(index_elements=_VINTAGE_KEY)
            .returning(EconomicEventScheduleVintageRow.id)
        )
        inserted_id = (await self._session.execute(stmt)).scalar_one_or_none()
        if inserted_id is not None:
            await self._session.commit()
            return VintageWriteOutcome.INSERTED

        existing_row = await self._select_one_schedule(
            vintage.occurrence_key, vintage.revision_sequence
        )
        await self._session.commit()
        existing = _schedule_to_domain(existing_row)
        if existing == vintage:
            return VintageWriteOutcome.ALREADY_PRESENT
        raise EconomicEventVintageConflictError(existing, vintage)

    async def list_all_schedule_vintages(
        self, occurrence_key: str
    ) -> tuple[EconomicEventScheduleVintage, ...]:
        stmt = select(EconomicEventScheduleVintageRow).where(
            EconomicEventScheduleVintageRow.occurrence_key == occurrence_key
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        await self._session.commit()
        return tuple(_schedule_to_domain(row) for row in rows)

    async def schedule_as_of(
        self, occurrence_key: str, as_of: UtcTimestamp
    ) -> EconomicEventScheduleVintage | None:
        stmt = (
            select(EconomicEventScheduleVintageRow)
            .where(
                EconomicEventScheduleVintageRow.occurrence_key == occurrence_key,
                EconomicEventScheduleVintageRow.availability <= as_of.value,
            )
            .order_by(
                EconomicEventScheduleVintageRow.availability.desc(),
                EconomicEventScheduleVintageRow.revision_sequence.desc(),
            )
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _schedule_to_domain(row)

    # --- Consensus vintages -----------------------------------------------------

    async def add_consensus_vintage(
        self, vintage: EconomicEventConsensusVintage
    ) -> VintageWriteOutcome:
        stmt = (
            pg_insert(EconomicEventConsensusVintageRow)
            .values(_consensus_row_values(vintage))
            .on_conflict_do_nothing(index_elements=_VINTAGE_KEY)
            .returning(EconomicEventConsensusVintageRow.id)
        )
        inserted_id = (await self._session.execute(stmt)).scalar_one_or_none()
        if inserted_id is not None:
            await self._session.commit()
            return VintageWriteOutcome.INSERTED

        existing_row = await self._select_one_consensus(
            vintage.occurrence_key, vintage.revision_sequence
        )
        await self._session.commit()
        existing = _consensus_to_domain(existing_row)
        if existing == vintage:
            return VintageWriteOutcome.ALREADY_PRESENT
        raise EconomicEventVintageConflictError(existing, vintage)

    async def list_all_consensus_vintages(
        self, occurrence_key: str
    ) -> tuple[EconomicEventConsensusVintage, ...]:
        stmt = select(EconomicEventConsensusVintageRow).where(
            EconomicEventConsensusVintageRow.occurrence_key == occurrence_key
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        await self._session.commit()
        return tuple(_consensus_to_domain(row) for row in rows)

    async def consensus_as_of(
        self, occurrence_key: str, as_of: UtcTimestamp
    ) -> EconomicEventConsensusVintage | None:
        stmt = (
            select(EconomicEventConsensusVintageRow)
            .where(
                EconomicEventConsensusVintageRow.occurrence_key == occurrence_key,
                EconomicEventConsensusVintageRow.availability <= as_of.value,
            )
            .order_by(
                EconomicEventConsensusVintageRow.availability.desc(),
                EconomicEventConsensusVintageRow.revision_sequence.desc(),
            )
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _consensus_to_domain(row)

    # --- Actual-value vintages ---------------------------------------------------

    async def add_actual_value_vintage(
        self, vintage: EconomicEventActualValueVintage
    ) -> VintageWriteOutcome:
        stmt = (
            pg_insert(EconomicEventActualValueVintageRow)
            .values(_actual_row_values(vintage))
            .on_conflict_do_nothing(index_elements=_VINTAGE_KEY)
            .returning(EconomicEventActualValueVintageRow.id)
        )
        inserted_id = (await self._session.execute(stmt)).scalar_one_or_none()
        if inserted_id is not None:
            await self._session.commit()
            return VintageWriteOutcome.INSERTED

        existing_row = await self._select_one_actual(
            vintage.occurrence_key, vintage.revision_sequence
        )
        await self._session.commit()
        existing = _actual_to_domain(existing_row)
        if existing == vintage:
            return VintageWriteOutcome.ALREADY_PRESENT
        raise EconomicEventVintageConflictError(existing, vintage)

    async def list_all_actual_value_vintages(
        self, occurrence_key: str
    ) -> tuple[EconomicEventActualValueVintage, ...]:
        stmt = select(EconomicEventActualValueVintageRow).where(
            EconomicEventActualValueVintageRow.occurrence_key == occurrence_key
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        await self._session.commit()
        return tuple(_actual_to_domain(row) for row in rows)

    async def actual_value_as_of(
        self, occurrence_key: str, as_of: UtcTimestamp
    ) -> EconomicEventActualValueVintage | None:
        stmt = (
            select(EconomicEventActualValueVintageRow)
            .where(
                EconomicEventActualValueVintageRow.occurrence_key == occurrence_key,
                EconomicEventActualValueVintageRow.availability <= as_of.value,
            )
            .order_by(
                EconomicEventActualValueVintageRow.availability.desc(),
                EconomicEventActualValueVintageRow.revision_sequence.desc(),
            )
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _actual_to_domain(row)

    async def first_release_as_of(
        self, occurrence_key: str, as_of: UtcTimestamp
    ) -> EconomicEventActualValueVintage | None:
        stmt = select(EconomicEventActualValueVintageRow).where(
            EconomicEventActualValueVintageRow.occurrence_key == occurrence_key,
            EconomicEventActualValueVintageRow.revision_sequence == 0,
            EconomicEventActualValueVintageRow.availability <= as_of.value,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _actual_to_domain(row)

    # --- Release vintages (FX-51H) -----------------------------------------------

    async def add_release_vintage(
        self, vintage: EconomicEventReleaseVintage
    ) -> VintageWriteOutcome:
        stmt = (
            pg_insert(EconomicEventReleaseVintageRow)
            .values(_release_row_values(vintage))
            .on_conflict_do_nothing(index_elements=_VINTAGE_KEY)
            .returning(EconomicEventReleaseVintageRow.id)
        )
        inserted_id = (await self._session.execute(stmt)).scalar_one_or_none()
        if inserted_id is not None:
            await self._session.commit()
            return VintageWriteOutcome.INSERTED

        existing_row = await self._select_one_release(
            vintage.occurrence_key, vintage.revision_sequence
        )
        await self._session.commit()
        existing = _release_to_domain(existing_row)
        if existing == vintage:
            return VintageWriteOutcome.ALREADY_PRESENT
        raise EconomicEventVintageConflictError(existing, vintage)

    async def list_all_release_vintages(
        self, occurrence_key: str
    ) -> tuple[EconomicEventReleaseVintage, ...]:
        stmt = select(EconomicEventReleaseVintageRow).where(
            EconomicEventReleaseVintageRow.occurrence_key == occurrence_key
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        await self._session.commit()
        return tuple(_release_to_domain(row) for row in rows)

    async def release_as_of(
        self, occurrence_key: str, as_of: UtcTimestamp
    ) -> EconomicEventReleaseVintage | None:
        stmt = (
            select(EconomicEventReleaseVintageRow)
            .where(
                EconomicEventReleaseVintageRow.occurrence_key == occurrence_key,
                EconomicEventReleaseVintageRow.availability <= as_of.value,
            )
            .order_by(
                EconomicEventReleaseVintageRow.availability.desc(),
                EconomicEventReleaseVintageRow.revision_sequence.desc(),
            )
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _release_to_domain(row)

    # --- Window query ------------------------------------------------------------

    async def known_events_in_window(
        self, start: UtcTimestamp, end: UtcTimestamp, as_of: UtcTimestamp
    ) -> tuple[tuple[EconomicEventOccurrence, EconomicEventScheduleVintage], ...]:
        s = EconomicEventScheduleVintageRow
        # Rank + availability-filter only, in SQL -- explicit, individually
        # labeled columns, never `select(s, ...)` (the whole ORM entity),
        # whose column order in the resulting subquery is an implementation
        # detail this method must not depend on. Every value below is read
        # back by its own label name (`row._mapping[...]`), never by
        # position. The actual window-membership test (a true UTC instant
        # or local-day-range comparison, never a naive date compare) runs
        # in Python afterward via `schedule_within_window`.
        ranked = (
            select(
                s.occurrence_key.label("occurrence_key"),
                s.revision_sequence.label("revision_sequence"),
                s.scheduled_date.label("scheduled_date"),
                s.scheduled_time.label("scheduled_time"),
                s.schedule_timezone.label("schedule_timezone"),
                s.status.label("status"),
                s.availability.label("availability"),
                s.availability_confidence.label("availability_confidence"),
                s.source.label("source"),
                func.row_number()
                .over(
                    partition_by=s.occurrence_key,
                    order_by=(s.availability.desc(), s.revision_sequence.desc()),
                )
                .label("rn"),
            )
            .where(s.availability <= as_of.value)
            .subquery()
        )
        occurrence = EconomicEventOccurrenceRow
        stmt = (
            select(occurrence, ranked)
            .join(occurrence, occurrence.occurrence_key == ranked.c.occurrence_key)
            .where(ranked.c.rn == 1)
        )
        rows = (await self._session.execute(stmt)).all()
        await self._session.commit()
        results = []
        for row in rows:
            m = row._mapping
            occurrence_row = m[EconomicEventOccurrenceRow]
            availability = m["availability"]
            schedule = EconomicEventScheduleVintage(
                occurrence_key=m["occurrence_key"],
                revision_sequence=m["revision_sequence"],
                scheduled_date=m["scheduled_date"],
                scheduled_time=m["scheduled_time"],
                schedule_timezone=m["schedule_timezone"],
                status=EconomicEventStatus(m["status"]),
                availability=None if availability is None else UtcTimestamp(availability),
                availability_confidence=AvailabilityConfidence(m["availability_confidence"]),
                source=m["source"],
            )
            if schedule_within_window(schedule, start, end):
                results.append((_occurrence_to_domain(occurrence_row), schedule))
        return tuple(results)

    # --- Internal lookups (diagnostic only, never decide a write outcome) -------

    async def _select_one_schedule(
        self, occurrence_key: str, revision_sequence: int
    ) -> EconomicEventScheduleVintageRow:
        stmt = select(EconomicEventScheduleVintageRow).where(
            EconomicEventScheduleVintageRow.occurrence_key == occurrence_key,
            EconomicEventScheduleVintageRow.revision_sequence == revision_sequence,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        assert row is not None  # the failed insert proves the identity already exists
        return row

    async def _select_one_consensus(
        self, occurrence_key: str, revision_sequence: int
    ) -> EconomicEventConsensusVintageRow:
        stmt = select(EconomicEventConsensusVintageRow).where(
            EconomicEventConsensusVintageRow.occurrence_key == occurrence_key,
            EconomicEventConsensusVintageRow.revision_sequence == revision_sequence,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        assert row is not None
        return row

    async def _select_one_actual(
        self, occurrence_key: str, revision_sequence: int
    ) -> EconomicEventActualValueVintageRow:
        stmt = select(EconomicEventActualValueVintageRow).where(
            EconomicEventActualValueVintageRow.occurrence_key == occurrence_key,
            EconomicEventActualValueVintageRow.revision_sequence == revision_sequence,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        assert row is not None
        return row

    async def _select_one_release(
        self, occurrence_key: str, revision_sequence: int
    ) -> EconomicEventReleaseVintageRow:
        stmt = select(EconomicEventReleaseVintageRow).where(
            EconomicEventReleaseVintageRow.occurrence_key == occurrence_key,
            EconomicEventReleaseVintageRow.revision_sequence == revision_sequence,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        assert row is not None
        return row


def _occurrence_to_domain(row: EconomicEventOccurrenceRow) -> EconomicEventOccurrence:
    return EconomicEventOccurrence(
        occurrence_key=row.occurrence_key,
        indicator_key=row.indicator_key,
        reference_period=(
            None if row.reference_period is None else UtcTimestamp(row.reference_period)
        ),
        release_group_key=row.release_group_key,
    )


def _schedule_row_values(vintage: EconomicEventScheduleVintage) -> dict[str, object]:
    return {
        "occurrence_key": vintage.occurrence_key,
        "revision_sequence": vintage.revision_sequence,
        "scheduled_date": vintage.scheduled_date,
        "scheduled_time": vintage.scheduled_time,
        "schedule_timezone": vintage.schedule_timezone,
        "status": vintage.status.value,
        "availability": None if vintage.availability is None else vintage.availability.value,
        "availability_confidence": vintage.availability_confidence.value,
        "source": vintage.source,
    }


def _schedule_to_domain(row: EconomicEventScheduleVintageRow) -> EconomicEventScheduleVintage:
    return EconomicEventScheduleVintage(
        occurrence_key=row.occurrence_key,
        revision_sequence=row.revision_sequence,
        scheduled_date=row.scheduled_date,
        scheduled_time=row.scheduled_time,
        schedule_timezone=row.schedule_timezone,
        status=EconomicEventStatus(row.status),
        availability=None if row.availability is None else UtcTimestamp(row.availability),
        availability_confidence=AvailabilityConfidence(row.availability_confidence),
        source=row.source,
    )


def _consensus_row_values(vintage: EconomicEventConsensusVintage) -> dict[str, object]:
    return {
        "occurrence_key": vintage.occurrence_key,
        "revision_sequence": vintage.revision_sequence,
        "consensus_value": vintage.consensus_value,
        "availability": None if vintage.availability is None else vintage.availability.value,
        "availability_confidence": vintage.availability_confidence.value,
        "source": vintage.source,
        "raw_source_value": vintage.raw_source_value,
    }


def _consensus_to_domain(row: EconomicEventConsensusVintageRow) -> EconomicEventConsensusVintage:
    return EconomicEventConsensusVintage(
        occurrence_key=row.occurrence_key,
        revision_sequence=row.revision_sequence,
        consensus_value=row.consensus_value,
        availability=None if row.availability is None else UtcTimestamp(row.availability),
        availability_confidence=AvailabilityConfidence(row.availability_confidence),
        source=row.source,
        raw_source_value=row.raw_source_value,
    )


def _actual_row_values(vintage: EconomicEventActualValueVintage) -> dict[str, object]:
    return {
        "occurrence_key": vintage.occurrence_key,
        "revision_sequence": vintage.revision_sequence,
        "actual_value": vintage.actual_value,
        "availability": None if vintage.availability is None else vintage.availability.value,
        "availability_confidence": vintage.availability_confidence.value,
        "source": vintage.source,
        "raw_source_value": vintage.raw_source_value,
    }


def _actual_to_domain(
    row: EconomicEventActualValueVintageRow,
) -> EconomicEventActualValueVintage:
    return EconomicEventActualValueVintage(
        occurrence_key=row.occurrence_key,
        revision_sequence=row.revision_sequence,
        actual_value=row.actual_value,
        availability=None if row.availability is None else UtcTimestamp(row.availability),
        availability_confidence=AvailabilityConfidence(row.availability_confidence),
        source=row.source,
        raw_source_value=row.raw_source_value,
    )


def _release_row_values(vintage: EconomicEventReleaseVintage) -> dict[str, object]:
    return {
        "occurrence_key": vintage.occurrence_key,
        "revision_sequence": vintage.revision_sequence,
        "released_date": vintage.released_date,
        "released_time": vintage.released_time,
        "released_timezone": vintage.released_timezone,
        "availability": None if vintage.availability is None else vintage.availability.value,
        "availability_confidence": vintage.availability_confidence.value,
        "source": vintage.source,
    }


def _release_to_domain(row: EconomicEventReleaseVintageRow) -> EconomicEventReleaseVintage:
    return EconomicEventReleaseVintage(
        occurrence_key=row.occurrence_key,
        revision_sequence=row.revision_sequence,
        released_date=row.released_date,
        released_time=row.released_time,
        released_timezone=row.released_timezone,
        availability=None if row.availability is None else UtcTimestamp(row.availability),
        availability_confidence=AvailabilityConfidence(row.availability_confidence),
        source=row.source,
    )
