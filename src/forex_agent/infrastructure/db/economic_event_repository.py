"""SQLAlchemy implementation of `EconomicEventRepository` (FX-51).

Enforces the point-in-time invariant ("a query at T cannot return a
vintage whose availability is None or after T") entirely through each
`*_as_of` method's own `WHERE availability <= :as_of` clause -- there is
deliberately no separate "safety check" layered on top; the SQL
predicate IS the safety guarantee, exactly as
`SqlAlchemyMacroObservationRepository` (FX-41) already established.
Every write is a plain `INSERT ... ON CONFLICT DO NOTHING` -- no method
in this class ever issues an UPDATE, so a historical vintage row can
never be mutated once stored.

`known_events_in_window`'s own date-range filter deliberately compares
`scheduled_date` (a plain calendar date, in the schedule's OWN local
timezone) against `start`/`end` converted to their UTC calendar dates --
NOT a fully timezone-resolved instant-range check. This is a stated,
deliberate simplification (FX-51 Section 26: "do not overengineer"): an
event scheduled very late or very early in a local day whose UTC
calendar date differs from its local one could, in principle, fall on
the "wrong" side of a window boundary by one day. Documented as a known
limitation rather than solved with a fragile, hard-to-verify per-row
dynamic-timezone SQL conversion within this story's own scope.
"""

from sqlalchemy import func, select
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
from forex_agent.domain.economic_event_schedule_vintage import EconomicEventScheduleVintage
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
from forex_agent.infrastructure.db.models.economic_event_schedule_vintage import (
    EconomicEventScheduleVintageRow,
)

_OCCURRENCE_KEY = ("indicator_key", "reference_period")
_VINTAGE_KEY = ("indicator_key", "reference_period", "revision_sequence")


class SqlAlchemyEconomicEventRepository:
    """Implements `EconomicEventRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- Occurrences ---------------------------------------------------------

    async def add_occurrence(self, occurrence: EconomicEventOccurrence) -> VintageWriteOutcome:
        stmt = (
            pg_insert(EconomicEventOccurrenceRow)
            .values(
                indicator_key=occurrence.indicator_key,
                reference_period=occurrence.reference_period.value,
                release_group_key=occurrence.release_group_key,
            )
            .on_conflict_do_nothing(index_elements=_OCCURRENCE_KEY)
            .returning(EconomicEventOccurrenceRow.id)
        )
        inserted_id = (await self._session.execute(stmt)).scalar_one_or_none()
        if inserted_id is not None:
            await self._session.commit()
            return VintageWriteOutcome.INSERTED

        existing = await self.get_occurrence(occurrence.indicator_key, occurrence.reference_period)
        await self._session.commit()
        assert existing is not None  # the failed insert proves the identity already exists
        if existing == occurrence:
            return VintageWriteOutcome.ALREADY_PRESENT
        raise EconomicEventOccurrenceConflictError(existing, occurrence)

    async def get_occurrence(
        self, indicator_key: str, reference_period: UtcTimestamp
    ) -> EconomicEventOccurrence | None:
        stmt = select(EconomicEventOccurrenceRow).where(
            EconomicEventOccurrenceRow.indicator_key == indicator_key,
            EconomicEventOccurrenceRow.reference_period == reference_period.value,
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
            vintage.indicator_key, vintage.reference_period, vintage.revision_sequence
        )
        await self._session.commit()
        existing = _schedule_to_domain(existing_row)
        if existing == vintage:
            return VintageWriteOutcome.ALREADY_PRESENT
        raise EconomicEventVintageConflictError(existing, vintage)

    async def list_all_schedule_vintages(
        self, indicator_key: str, reference_period: UtcTimestamp
    ) -> tuple[EconomicEventScheduleVintage, ...]:
        stmt = select(EconomicEventScheduleVintageRow).where(
            EconomicEventScheduleVintageRow.indicator_key == indicator_key,
            EconomicEventScheduleVintageRow.reference_period == reference_period.value,
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        await self._session.commit()
        return tuple(_schedule_to_domain(row) for row in rows)

    async def schedule_as_of(
        self, indicator_key: str, reference_period: UtcTimestamp, as_of: UtcTimestamp
    ) -> EconomicEventScheduleVintage | None:
        stmt = (
            select(EconomicEventScheduleVintageRow)
            .where(
                EconomicEventScheduleVintageRow.indicator_key == indicator_key,
                EconomicEventScheduleVintageRow.reference_period == reference_period.value,
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
            vintage.indicator_key, vintage.reference_period, vintage.revision_sequence
        )
        await self._session.commit()
        existing = _consensus_to_domain(existing_row)
        if existing == vintage:
            return VintageWriteOutcome.ALREADY_PRESENT
        raise EconomicEventVintageConflictError(existing, vintage)

    async def list_all_consensus_vintages(
        self, indicator_key: str, reference_period: UtcTimestamp
    ) -> tuple[EconomicEventConsensusVintage, ...]:
        stmt = select(EconomicEventConsensusVintageRow).where(
            EconomicEventConsensusVintageRow.indicator_key == indicator_key,
            EconomicEventConsensusVintageRow.reference_period == reference_period.value,
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        await self._session.commit()
        return tuple(_consensus_to_domain(row) for row in rows)

    async def consensus_as_of(
        self, indicator_key: str, reference_period: UtcTimestamp, as_of: UtcTimestamp
    ) -> EconomicEventConsensusVintage | None:
        stmt = (
            select(EconomicEventConsensusVintageRow)
            .where(
                EconomicEventConsensusVintageRow.indicator_key == indicator_key,
                EconomicEventConsensusVintageRow.reference_period == reference_period.value,
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
            vintage.indicator_key, vintage.reference_period, vintage.revision_sequence
        )
        await self._session.commit()
        existing = _actual_to_domain(existing_row)
        if existing == vintage:
            return VintageWriteOutcome.ALREADY_PRESENT
        raise EconomicEventVintageConflictError(existing, vintage)

    async def list_all_actual_value_vintages(
        self, indicator_key: str, reference_period: UtcTimestamp
    ) -> tuple[EconomicEventActualValueVintage, ...]:
        stmt = select(EconomicEventActualValueVintageRow).where(
            EconomicEventActualValueVintageRow.indicator_key == indicator_key,
            EconomicEventActualValueVintageRow.reference_period == reference_period.value,
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        await self._session.commit()
        return tuple(_actual_to_domain(row) for row in rows)

    async def actual_value_as_of(
        self, indicator_key: str, reference_period: UtcTimestamp, as_of: UtcTimestamp
    ) -> EconomicEventActualValueVintage | None:
        stmt = (
            select(EconomicEventActualValueVintageRow)
            .where(
                EconomicEventActualValueVintageRow.indicator_key == indicator_key,
                EconomicEventActualValueVintageRow.reference_period == reference_period.value,
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
        self, indicator_key: str, reference_period: UtcTimestamp, as_of: UtcTimestamp
    ) -> EconomicEventActualValueVintage | None:
        stmt = select(EconomicEventActualValueVintageRow).where(
            EconomicEventActualValueVintageRow.indicator_key == indicator_key,
            EconomicEventActualValueVintageRow.reference_period == reference_period.value,
            EconomicEventActualValueVintageRow.revision_sequence == 0,
            EconomicEventActualValueVintageRow.availability <= as_of.value,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _actual_to_domain(row)

    # --- Window query ------------------------------------------------------------

    async def known_events_in_window(
        self, start: UtcTimestamp, end: UtcTimestamp, as_of: UtcTimestamp
    ) -> tuple[tuple[EconomicEventOccurrence, EconomicEventScheduleVintage], ...]:
        s = EconomicEventScheduleVintageRow
        # Explicit, individually-labeled columns only -- never `select(s,
        # ...)` (the whole ORM entity), whose column order in the
        # resulting subquery is an implementation detail this method must
        # not depend on. Every value below is read back by its own label
        # name (`row._mapping[...]`), never by position.
        ranked = (
            select(
                s.indicator_key.label("indicator_key"),
                s.reference_period.label("reference_period"),
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
                    partition_by=(s.indicator_key, s.reference_period),
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
            .join(
                occurrence,
                (occurrence.indicator_key == ranked.c.indicator_key)
                & (occurrence.reference_period == ranked.c.reference_period),
            )
            .where(
                ranked.c.rn == 1,
                ranked.c.scheduled_date >= start.value.date(),
                ranked.c.scheduled_date < end.value.date(),
            )
        )
        rows = (await self._session.execute(stmt)).all()
        await self._session.commit()
        results = []
        for row in rows:
            m = row._mapping
            occurrence_row = m[EconomicEventOccurrenceRow]
            availability = m["availability"]
            schedule = EconomicEventScheduleVintage(
                indicator_key=m["indicator_key"],
                reference_period=UtcTimestamp(m["reference_period"]),
                revision_sequence=m["revision_sequence"],
                scheduled_date=m["scheduled_date"],
                scheduled_time=m["scheduled_time"],
                schedule_timezone=m["schedule_timezone"],
                status=EconomicEventStatus(m["status"]),
                availability=None if availability is None else UtcTimestamp(availability),
                availability_confidence=AvailabilityConfidence(m["availability_confidence"]),
                source=m["source"],
            )
            results.append((_occurrence_to_domain(occurrence_row), schedule))
        return tuple(results)

    # --- Internal lookups (diagnostic only, never decide a write outcome) -------

    async def _select_one_schedule(
        self, indicator_key: str, reference_period: UtcTimestamp, revision_sequence: int
    ) -> EconomicEventScheduleVintageRow:
        stmt = select(EconomicEventScheduleVintageRow).where(
            EconomicEventScheduleVintageRow.indicator_key == indicator_key,
            EconomicEventScheduleVintageRow.reference_period == reference_period.value,
            EconomicEventScheduleVintageRow.revision_sequence == revision_sequence,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        assert row is not None  # the failed insert proves the identity already exists
        return row

    async def _select_one_consensus(
        self, indicator_key: str, reference_period: UtcTimestamp, revision_sequence: int
    ) -> EconomicEventConsensusVintageRow:
        stmt = select(EconomicEventConsensusVintageRow).where(
            EconomicEventConsensusVintageRow.indicator_key == indicator_key,
            EconomicEventConsensusVintageRow.reference_period == reference_period.value,
            EconomicEventConsensusVintageRow.revision_sequence == revision_sequence,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        assert row is not None
        return row

    async def _select_one_actual(
        self, indicator_key: str, reference_period: UtcTimestamp, revision_sequence: int
    ) -> EconomicEventActualValueVintageRow:
        stmt = select(EconomicEventActualValueVintageRow).where(
            EconomicEventActualValueVintageRow.indicator_key == indicator_key,
            EconomicEventActualValueVintageRow.reference_period == reference_period.value,
            EconomicEventActualValueVintageRow.revision_sequence == revision_sequence,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        assert row is not None
        return row


def _occurrence_to_domain(row: EconomicEventOccurrenceRow) -> EconomicEventOccurrence:
    return EconomicEventOccurrence(
        indicator_key=row.indicator_key,
        reference_period=UtcTimestamp(row.reference_period),
        release_group_key=row.release_group_key,
    )


def _schedule_row_values(vintage: EconomicEventScheduleVintage) -> dict[str, object]:
    return {
        "indicator_key": vintage.indicator_key,
        "reference_period": vintage.reference_period.value,
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
        indicator_key=row.indicator_key,
        reference_period=UtcTimestamp(row.reference_period),
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
        "indicator_key": vintage.indicator_key,
        "reference_period": vintage.reference_period.value,
        "revision_sequence": vintage.revision_sequence,
        "consensus_value": vintage.consensus_value,
        "availability": None if vintage.availability is None else vintage.availability.value,
        "availability_confidence": vintage.availability_confidence.value,
        "source": vintage.source,
        "raw_source_value": vintage.raw_source_value,
    }


def _consensus_to_domain(row: EconomicEventConsensusVintageRow) -> EconomicEventConsensusVintage:
    return EconomicEventConsensusVintage(
        indicator_key=row.indicator_key,
        reference_period=UtcTimestamp(row.reference_period),
        revision_sequence=row.revision_sequence,
        consensus_value=row.consensus_value,
        availability=None if row.availability is None else UtcTimestamp(row.availability),
        availability_confidence=AvailabilityConfidence(row.availability_confidence),
        source=row.source,
        raw_source_value=row.raw_source_value,
    )


def _actual_row_values(vintage: EconomicEventActualValueVintage) -> dict[str, object]:
    return {
        "indicator_key": vintage.indicator_key,
        "reference_period": vintage.reference_period.value,
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
        indicator_key=row.indicator_key,
        reference_period=UtcTimestamp(row.reference_period),
        revision_sequence=row.revision_sequence,
        actual_value=row.actual_value,
        availability=None if row.availability is None else UtcTimestamp(row.availability),
        availability_confidence=AvailabilityConfidence(row.availability_confidence),
        source=row.source,
        raw_source_value=row.raw_source_value,
    )
