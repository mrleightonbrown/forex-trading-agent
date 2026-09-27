"""FX-52A: integration tests for `IngestOfficialCalendarSchedule`/
`IngestOfficialCalendarRelease` against `SqlAlchemyEconomicEventRepository`
and live Postgres -- proves the full round-trip (raw observation ->
occurrence/vintage persistence -> PIT `*_as_of` queries) on top of the
already-hardened FX-51/FX-51H/FX-51H.1 model, not just the use cases'
own in-memory logic.
"""

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, time

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.application.ports.economic_calendar_source import (
    RawReleaseObservation,
    RawScheduleObservation,
)
from forex_agent.application.use_cases.ingest_official_calendar_release import (
    IngestOfficialCalendarRelease,
    ReleaseIngestionDisposition,
)
from forex_agent.application.use_cases.ingest_official_calendar_schedule import (
    IngestOfficialCalendarSchedule,
    ScheduleIngestionDisposition,
)
from forex_agent.domain.economic_event_status import EconomicEventStatus
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.economic_event_repository import (
    SqlAlchemyEconomicEventRepository,
)
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
from forex_agent.infrastructure.db.session import get_engine

_SOURCE = "__TEST_SOURCE__"


def _ts(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> UtcTimestamp:
    return UtcTimestamp(datetime(year, month, day, hour, minute, tzinfo=UTC))


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    async with session_factory() as db_session:
        yield db_session

    async with session_factory() as cleanup_session:
        for row_type in (
            EconomicEventScheduleVintageRow,
            EconomicEventConsensusVintageRow,
            EconomicEventActualValueVintageRow,
            EconomicEventReleaseVintageRow,
        ):
            await cleanup_session.execute(
                delete(row_type).where(row_type.occurrence_key.startswith(_SOURCE))
            )
        await cleanup_session.execute(
            delete(EconomicEventOccurrenceRow).where(
                EconomicEventOccurrenceRow.occurrence_key.startswith(_SOURCE)
            )
        )
        await cleanup_session.commit()


def _schedule_observation(
    external_event_id: str,
    indicator_keys: tuple[str, ...],
    scheduled_date: date,
    observed_at: UtcTimestamp,
    scheduled_time: time | None = time(8, 30),
    status: EconomicEventStatus = EconomicEventStatus.SCHEDULED,
    reference_period: UtcTimestamp | None = None,
) -> RawScheduleObservation:
    return RawScheduleObservation(
        source=_SOURCE,
        external_event_id=external_event_id,
        indicator_keys=indicator_keys,
        scheduled_date=scheduled_date,
        scheduled_time=scheduled_time,
        schedule_timezone="America/New_York",
        status=status,
        observed_at=observed_at,
        raw_title="Test Release",
        reference_period=reference_period,
    )


def _release_observation(
    external_event_id: str,
    indicator_keys: tuple[str, ...],
    released_date: date,
    observed_at: UtcTimestamp,
    released_time: time | None = time(8, 30),
) -> RawReleaseObservation:
    return RawReleaseObservation(
        source=_SOURCE,
        external_event_id=external_event_id,
        indicator_keys=indicator_keys,
        released_date=released_date,
        released_time=released_time,
        released_timezone="America/New_York",
        observed_at=observed_at,
        raw_title="Test Release Evidence",
    )


# ---------------------------------------------------------------------------
# Occurrence identity / schedule ingestion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_observation_creates_occurrence_and_schedule(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    use_case = IngestOfficialCalendarSchedule(repo)
    observation = _schedule_observation(
        "ev1", ("US_CPI_YOY",), date(2026, 12, 10), _ts(2026, 11, 1)
    )

    results = await use_case((observation,))

    assert len(results) == 1
    assert results[0].disposition is ScheduleIngestionDisposition.NEW_OCCURRENCE
    occurrence = await repo.get_occurrence(results[0].occurrence_key)
    assert occurrence is not None
    assert occurrence.indicator_key == "US_CPI_YOY"
    schedule = await repo.schedule_as_of(results[0].occurrence_key, _ts(2026, 11, 2))
    assert schedule is not None
    assert schedule.scheduled_date == date(2026, 12, 10)
    assert schedule.availability_confidence.name == "ESTIMATED"


@pytest.mark.asyncio
async def test_repeated_identical_poll_is_unchanged_no_new_vintage(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    use_case = IngestOfficialCalendarSchedule(repo)
    observation = _schedule_observation(
        "ev2", ("US_CPI_YOY",), date(2026, 12, 10), _ts(2026, 11, 1)
    )

    first = await use_case((observation,))
    second_observation = _schedule_observation(
        "ev2", ("US_CPI_YOY",), date(2026, 12, 10), _ts(2026, 11, 2)
    )
    second = await use_case((second_observation,))

    assert first[0].disposition is ScheduleIngestionDisposition.NEW_OCCURRENCE
    assert second[0].disposition is ScheduleIngestionDisposition.UNCHANGED
    vintages = await repo.list_all_schedule_vintages(first[0].occurrence_key)
    assert len(vintages) == 1


@pytest.mark.asyncio
async def test_reschedule_preserves_occurrence_key_and_adds_vintage(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    use_case = IngestOfficialCalendarSchedule(repo)
    original = _schedule_observation("ev3", ("US_CPI_YOY",), date(2026, 12, 10), _ts(2026, 11, 1))
    rescheduled = _schedule_observation(
        "ev3", ("US_CPI_YOY",), date(2026, 12, 12), _ts(2026, 11, 5)
    )

    first = await use_case((original,))
    second = await use_case((rescheduled,))

    assert first[0].occurrence_key == second[0].occurrence_key
    assert second[0].disposition is ScheduleIngestionDisposition.RESCHEDULED

    before = await repo.schedule_as_of(first[0].occurrence_key, _ts(2026, 11, 3))
    after = await repo.schedule_as_of(first[0].occurrence_key, _ts(2026, 11, 6))
    assert before is not None and before.scheduled_date == date(2026, 12, 10)
    assert after is not None and after.scheduled_date == date(2026, 12, 12)


@pytest.mark.asyncio
async def test_tbd_time_becomes_known_creates_new_vintage(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    use_case = IngestOfficialCalendarSchedule(repo)
    tbd = _schedule_observation(
        "ev4", ("US_CPI_YOY",), date(2026, 12, 10), _ts(2026, 11, 1), scheduled_time=None
    )
    known = _schedule_observation(
        "ev4", ("US_CPI_YOY",), date(2026, 12, 10), _ts(2026, 11, 5), scheduled_time=time(8, 30)
    )

    first = await use_case((tbd,))
    second = await use_case((known,))

    assert first[0].disposition is ScheduleIngestionDisposition.NEW_OCCURRENCE
    assert second[0].disposition is ScheduleIngestionDisposition.RESCHEDULED
    before = await repo.schedule_as_of(first[0].occurrence_key, _ts(2026, 11, 3))
    assert before is not None and before.scheduled_time is None


@pytest.mark.asyncio
async def test_explicit_cancellation_is_recorded(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    use_case = IngestOfficialCalendarSchedule(repo)
    scheduled = _schedule_observation("ev5", ("US_CPI_YOY",), date(2026, 12, 10), _ts(2026, 11, 1))
    cancelled = _schedule_observation(
        "ev5",
        ("US_CPI_YOY",),
        date(2026, 12, 10),
        _ts(2026, 11, 5),
        status=EconomicEventStatus.CANCELLED,
    )

    await use_case((scheduled,))
    results = await use_case((cancelled,))

    assert results[0].disposition is ScheduleIngestionDisposition.CANCELLED
    state = await repo.schedule_as_of(results[0].occurrence_key, _ts(2026, 11, 6))
    assert state is not None and state.status is EconomicEventStatus.CANCELLED


@pytest.mark.asyncio
async def test_reinstatement_after_postponement(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    use_case = IngestOfficialCalendarSchedule(repo)
    scheduled = _schedule_observation("ev6", ("US_CPI_YOY",), date(2026, 12, 10), _ts(2026, 11, 1))
    postponed = _schedule_observation(
        "ev6",
        ("US_CPI_YOY",),
        date(2026, 12, 10),
        _ts(2026, 11, 2),
        status=EconomicEventStatus.POSTPONED,
    )
    reinstated = _schedule_observation("ev6", ("US_CPI_YOY",), date(2027, 1, 15), _ts(2026, 11, 20))

    await use_case((scheduled,))
    postponed_result = await use_case((postponed,))
    reinstated_result = await use_case((reinstated,))

    assert postponed_result[0].disposition is ScheduleIngestionDisposition.POSTPONED
    assert reinstated_result[0].disposition is ScheduleIngestionDisposition.REINSTATED


@pytest.mark.asyncio
async def test_disappearance_from_feed_is_not_treated_as_cancellation(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    use_case = IngestOfficialCalendarSchedule(repo)
    observation = _schedule_observation(
        "ev7", ("US_CPI_YOY",), date(2026, 12, 10), _ts(2026, 11, 1)
    )

    first = await use_case((observation,))
    # Next poll's feed simply does not include this item at all --
    # never construct a CANCELLED observation from absence.
    await use_case(())

    state = await repo.schedule_as_of(first[0].occurrence_key, _ts(2026, 12, 1))
    assert state is not None
    assert state.status is EconomicEventStatus.SCHEDULED
    vintages = await repo.list_all_schedule_vintages(first[0].occurrence_key)
    assert len(vintages) == 1


@pytest.mark.asyncio
async def test_unmapped_indicator_is_reported_and_not_persisted(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    use_case = IngestOfficialCalendarSchedule(repo)
    observation = _schedule_observation(
        "ev8", ("SOME_UNKNOWN_INDICATOR",), date(2026, 12, 10), _ts(2026, 11, 1)
    )

    results = await use_case((observation,))

    assert results[0].disposition is ScheduleIngestionDisposition.UNMAPPED
    assert results[0].occurrence_key == ""


@pytest.mark.asyncio
async def test_release_package_shares_release_group_key(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    use_case = IngestOfficialCalendarSchedule(repo)
    observation = _schedule_observation(
        "ev9",
        ("US_NONFARM_PAYROLLS", "US_UNEMPLOYMENT_RATE"),
        date(2026, 12, 4),
        _ts(2026, 11, 1),
    )

    results = await use_case((observation,))

    assert len(results) == 2
    occurrence_a = await repo.get_occurrence(results[0].occurrence_key)
    occurrence_b = await repo.get_occurrence(results[1].occurrence_key)
    assert occurrence_a is not None and occurrence_b is not None
    assert occurrence_a.release_group_key == occurrence_b.release_group_key
    assert occurrence_a.occurrence_key != occurrence_b.occurrence_key


@pytest.mark.asyncio
async def test_reference_period_preserved_when_source_establishes_it(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    use_case = IngestOfficialCalendarSchedule(repo)
    observation = _schedule_observation(
        "ev10",
        ("US_CPI_YOY",),
        date(2026, 12, 10),
        _ts(2026, 11, 1),
        reference_period=_ts(2026, 11, 1),
    )

    results = await use_case((observation,))

    occurrence = await repo.get_occurrence(results[0].occurrence_key)
    assert occurrence is not None
    assert occurrence.reference_period == _ts(2026, 11, 1)


@pytest.mark.asyncio
async def test_qualitative_event_has_no_reference_period(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    use_case = IngestOfficialCalendarSchedule(repo)
    observation = _schedule_observation(
        "ev11", ("CAD_POLICY_RATE_DECISION",), date(2026, 12, 10), _ts(2026, 11, 1)
    )

    results = await use_case((observation,))

    occurrence = await repo.get_occurrence(results[0].occurrence_key)
    assert occurrence is not None
    assert occurrence.reference_period is None


# ---------------------------------------------------------------------------
# Release-occurrence ingestion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_release_evidence_creates_release_vintage_distinct_from_availability(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    use_case = IngestOfficialCalendarRelease(repo)
    observation = _release_observation(
        "rel1",
        ("CAD_POLICY_RATE_DECISION",),
        date(2026, 9, 2),
        _ts(2026, 9, 2, 9, 50),
        released_time=time(9, 45),
    )

    results = await use_case((observation,))

    assert results[0].disposition is ReleaseIngestionDisposition.NEW_OCCURRENCE
    release = await repo.release_as_of(results[0].occurrence_key, _ts(2026, 9, 2, 10, 0))
    assert release is not None
    assert release.released_time == time(9, 45)
    assert release.availability == _ts(2026, 9, 2, 9, 50)
    assert release.released_time != release.availability.value.time()


@pytest.mark.asyncio
async def test_repeated_release_evidence_is_idempotent(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    use_case = IngestOfficialCalendarRelease(repo)
    observation = _release_observation(
        "rel2", ("CAD_POLICY_RATE_DECISION",), date(2026, 9, 2), _ts(2026, 9, 2, 9, 50)
    )

    first = await use_case((observation,))
    second_observation = _release_observation(
        "rel2", ("CAD_POLICY_RATE_DECISION",), date(2026, 9, 2), _ts(2026, 9, 2, 10, 0)
    )
    second = await use_case((second_observation,))

    assert first[0].disposition is ReleaseIngestionDisposition.NEW_OCCURRENCE
    assert second[0].disposition is ReleaseIngestionDisposition.UNCHANGED
    vintages = await repo.list_all_release_vintages(first[0].occurrence_key)
    assert len(vintages) == 1


@pytest.mark.asyncio
async def test_release_correlates_to_existing_scheduled_occurrence_by_date(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    schedule_use_case = IngestOfficialCalendarSchedule(repo)
    release_use_case = IngestOfficialCalendarRelease(repo)

    schedule_observation = _schedule_observation(
        "sched1", ("CAD_POLICY_RATE_DECISION",), date(2026, 10, 28), _ts(2026, 9, 1)
    )
    schedule_results = await schedule_use_case((schedule_observation,))

    # A DIFFERENT external_event_id (a separate press-release feed) for
    # the same real announcement, correlated purely by matching date.
    release_observation = _release_observation(
        "different_feed_id_999",
        ("CAD_POLICY_RATE_DECISION",),
        date(2026, 10, 28),
        _ts(2026, 10, 28, 13, 50),
    )
    release_results = await release_use_case((release_observation,))

    assert release_results[0].occurrence_key == schedule_results[0].occurrence_key


@pytest.mark.asyncio
async def test_release_without_matching_schedule_creates_new_occurrence(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    release_use_case = IngestOfficialCalendarRelease(repo)
    observation = _release_observation(
        "rel3", ("CAD_POLICY_RATE_DECISION",), date(2026, 12, 9), _ts(2026, 12, 9, 9, 50)
    )

    results = await release_use_case((observation,))

    occurrence = await repo.get_occurrence(results[0].occurrence_key)
    assert occurrence is not None


@pytest.mark.asyncio
async def test_unmapped_release_indicator_is_reported(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    use_case = IngestOfficialCalendarRelease(repo)
    observation = _release_observation(
        "rel4", ("SOME_UNKNOWN_INDICATOR",), date(2026, 9, 2), _ts(2026, 9, 2, 9, 50)
    )

    results = await use_case((observation,))

    assert results[0].disposition is ReleaseIngestionDisposition.UNMAPPED
