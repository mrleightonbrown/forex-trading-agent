"""FX-52A: integration tests for `IngestOfficialCalendarSchedule`/
`IngestOfficialCalendarRelease` against `SqlAlchemyEconomicEventRepository`
and live Postgres -- proves the full round-trip (raw observation ->
occurrence/vintage persistence -> PIT `*_as_of` queries) on top of the
already-hardened FX-51/FX-51H/FX-51H.1 model, not just the use cases'
own in-memory logic. FX-52AH adds the persisted source-mapping
repository and its own correlation-reconciliation test coverage
(exactly-one/zero/multiple candidates, persisted correlation surviving
a second poll).
"""

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, time

import pytest
from sqlalchemy import delete, select
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
from forex_agent.domain.economic_event_release_vintage import EconomicEventReleaseVintage
from forex_agent.domain.economic_event_status import EconomicEventStatus
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.economic_event_repository import (
    SqlAlchemyEconomicEventRepository,
)
from forex_agent.infrastructure.db.economic_event_source_mapping_repository import (
    SqlAlchemyEconomicEventSourceMappingRepository,
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
from forex_agent.infrastructure.db.models.economic_event_source_mapping import (
    EconomicEventSourceMappingRow,
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
        # occurrence_key is provider-neutral (FX-52AH) -- it is never
        # derived from _SOURCE, so identify test-created occurrences via
        # the mapping table (the one place _SOURCE is actually recorded)
        # rather than by pattern-matching the key itself.
        mapping_rows = (
            (
                await cleanup_session.execute(
                    select(EconomicEventSourceMappingRow.occurrence_key).where(
                        EconomicEventSourceMappingRow.source == _SOURCE
                    )
                )
            )
            .scalars()
            .all()
        )
        occurrence_keys = set(mapping_rows)
        if occurrence_keys:
            for row_type in (
                EconomicEventScheduleVintageRow,
                EconomicEventConsensusVintageRow,
                EconomicEventActualValueVintageRow,
                EconomicEventReleaseVintageRow,
            ):
                await cleanup_session.execute(
                    delete(row_type).where(row_type.occurrence_key.in_(occurrence_keys))
                )
        await cleanup_session.execute(
            delete(EconomicEventSourceMappingRow).where(
                EconomicEventSourceMappingRow.source == _SOURCE
            )
        )
        if occurrence_keys:
            await cleanup_session.execute(
                delete(EconomicEventOccurrenceRow).where(
                    EconomicEventOccurrenceRow.occurrence_key.in_(occurrence_keys)
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
    source: str = _SOURCE,
    source_published_at: UtcTimestamp | None = None,
) -> RawReleaseObservation:
    return RawReleaseObservation(
        source=source,
        external_event_id=external_event_id,
        indicator_keys=indicator_keys,
        released_date=released_date,
        released_time=released_time,
        released_timezone="America/New_York",
        observed_at=observed_at,
        raw_title="Test Release Evidence",
        source_published_at=source_published_at,
    )


# ---------------------------------------------------------------------------
# Occurrence identity / schedule ingestion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_observation_creates_occurrence_and_schedule(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    mapping_repo = SqlAlchemyEconomicEventSourceMappingRepository(session)
    use_case = IngestOfficialCalendarSchedule(repo, mapping_repo)
    observation = _schedule_observation(
        "ev1", ("US_CPI_YOY",), date(2026, 12, 10), _ts(2026, 11, 1)
    )

    results = await use_case((observation,))

    assert len(results) == 1
    assert results[0].disposition is ScheduleIngestionDisposition.NEW_OCCURRENCE
    occurrence = await repo.get_occurrence(results[0].occurrence_key)
    assert occurrence is not None
    assert occurrence.indicator_key == "US_CPI_YOY"
    # occurrence_key is NOT derived from source/external_event_id (FX-52AH).
    assert not results[0].occurrence_key.startswith(_SOURCE)
    schedule = await repo.schedule_as_of(results[0].occurrence_key, _ts(2026, 11, 2))
    assert schedule is not None
    assert schedule.scheduled_date == date(2026, 12, 10)
    assert schedule.availability_confidence.name == "ESTIMATED"


@pytest.mark.asyncio
async def test_repeated_identical_poll_is_unchanged_no_new_vintage(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    mapping_repo = SqlAlchemyEconomicEventSourceMappingRepository(session)
    use_case = IngestOfficialCalendarSchedule(repo, mapping_repo)
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
    assert second[0].occurrence_key == first[0].occurrence_key
    vintages = await repo.list_all_schedule_vintages(first[0].occurrence_key)
    assert len(vintages) == 1


@pytest.mark.asyncio
async def test_reschedule_preserves_occurrence_key_and_adds_vintage(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    mapping_repo = SqlAlchemyEconomicEventSourceMappingRepository(session)
    use_case = IngestOfficialCalendarSchedule(repo, mapping_repo)
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
    mapping_repo = SqlAlchemyEconomicEventSourceMappingRepository(session)
    use_case = IngestOfficialCalendarSchedule(repo, mapping_repo)
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
    mapping_repo = SqlAlchemyEconomicEventSourceMappingRepository(session)
    use_case = IngestOfficialCalendarSchedule(repo, mapping_repo)
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
    mapping_repo = SqlAlchemyEconomicEventSourceMappingRepository(session)
    use_case = IngestOfficialCalendarSchedule(repo, mapping_repo)
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
    mapping_repo = SqlAlchemyEconomicEventSourceMappingRepository(session)
    use_case = IngestOfficialCalendarSchedule(repo, mapping_repo)
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
    mapping_repo = SqlAlchemyEconomicEventSourceMappingRepository(session)
    use_case = IngestOfficialCalendarSchedule(repo, mapping_repo)
    observation = _schedule_observation(
        "ev8", ("SOME_UNKNOWN_INDICATOR",), date(2026, 12, 10), _ts(2026, 11, 1)
    )

    results = await use_case((observation,))

    assert results[0].disposition is ScheduleIngestionDisposition.UNMAPPED
    assert results[0].occurrence_key == ""


@pytest.mark.asyncio
async def test_release_package_shares_release_group_key(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    mapping_repo = SqlAlchemyEconomicEventSourceMappingRepository(session)
    use_case = IngestOfficialCalendarSchedule(repo, mapping_repo)
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
    mapping_repo = SqlAlchemyEconomicEventSourceMappingRepository(session)
    use_case = IngestOfficialCalendarSchedule(repo, mapping_repo)
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
    mapping_repo = SqlAlchemyEconomicEventSourceMappingRepository(session)
    use_case = IngestOfficialCalendarSchedule(repo, mapping_repo)
    observation = _schedule_observation(
        "ev11", ("CAD_POLICY_RATE_DECISION",), date(2026, 12, 10), _ts(2026, 11, 1)
    )

    results = await use_case((observation,))

    occurrence = await repo.get_occurrence(results[0].occurrence_key)
    assert occurrence is not None
    assert occurrence.reference_period is None


@pytest.mark.asyncio
async def test_mapping_repository_records_the_triple(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    mapping_repo = SqlAlchemyEconomicEventSourceMappingRepository(session)
    use_case = IngestOfficialCalendarSchedule(repo, mapping_repo)
    observation = _schedule_observation(
        "ev12", ("US_CPI_YOY",), date(2026, 12, 10), _ts(2026, 11, 1)
    )

    results = await use_case((observation,))

    stored = await mapping_repo.get_occurrence_key(_SOURCE, "ev12", "US_CPI_YOY")
    assert stored == results[0].occurrence_key


# ---------------------------------------------------------------------------
# Release-occurrence ingestion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_release_evidence_creates_release_vintage_distinct_from_availability(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    mapping_repo = SqlAlchemyEconomicEventSourceMappingRepository(session)
    use_case = IngestOfficialCalendarRelease(repo, mapping_repo)
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
    mapping_repo = SqlAlchemyEconomicEventSourceMappingRepository(session)
    use_case = IngestOfficialCalendarRelease(repo, mapping_repo)
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
    assert second[0].occurrence_key == first[0].occurrence_key
    vintages = await repo.list_all_release_vintages(first[0].occurrence_key)
    assert len(vintages) == 1


@pytest.mark.asyncio
async def test_release_correlates_to_existing_scheduled_occurrence_by_date(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    mapping_repo = SqlAlchemyEconomicEventSourceMappingRepository(session)
    schedule_use_case = IngestOfficialCalendarSchedule(repo, mapping_repo)
    release_use_case = IngestOfficialCalendarRelease(repo, mapping_repo)

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
    assert release_results[0].disposition is ReleaseIngestionDisposition.CORRELATED


@pytest.mark.asyncio
async def test_correlation_is_persisted_and_not_repeated_on_second_poll(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    mapping_repo = SqlAlchemyEconomicEventSourceMappingRepository(session)
    schedule_use_case = IngestOfficialCalendarSchedule(repo, mapping_repo)
    release_use_case = IngestOfficialCalendarRelease(repo, mapping_repo)

    schedule_observation = _schedule_observation(
        "sched2", ("CAD_POLICY_RATE_DECISION",), date(2026, 10, 28), _ts(2026, 9, 1)
    )
    schedule_results = await schedule_use_case((schedule_observation,))

    first_release = _release_observation(
        "release_feed_id_1", ("CAD_POLICY_RATE_DECISION",), date(2026, 10, 28), _ts(2026, 10, 28)
    )
    first_result = await release_use_case((first_release,))
    assert first_result[0].disposition is ReleaseIngestionDisposition.CORRELATED

    # A SECOND poll of the exact same (source, external_event_id) must
    # resolve via the now-persisted mapping, not repeat the date-match
    # heuristic -- and must not be CORRELATED again.
    second_release = _release_observation(
        "release_feed_id_1",
        ("CAD_POLICY_RATE_DECISION",),
        date(2026, 10, 28),
        _ts(2026, 10, 28, 14),
    )
    second_result = await release_use_case((second_release,))

    assert second_result[0].occurrence_key == schedule_results[0].occurrence_key
    assert second_result[0].disposition is ReleaseIngestionDisposition.UNCHANGED

    stored = await mapping_repo.get_occurrence_key(
        _SOURCE, "release_feed_id_1", "CAD_POLICY_RATE_DECISION"
    )
    assert stored == schedule_results[0].occurrence_key


@pytest.mark.asyncio
async def test_zero_candidates_creates_new_occurrence_lazily(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    mapping_repo = SqlAlchemyEconomicEventSourceMappingRepository(session)
    release_use_case = IngestOfficialCalendarRelease(repo, mapping_repo)
    observation = _release_observation(
        "rel3", ("CAD_POLICY_RATE_DECISION",), date(2026, 12, 9), _ts(2026, 12, 9, 9, 50)
    )

    results = await release_use_case((observation,))

    assert results[0].disposition is ReleaseIngestionDisposition.NEW_OCCURRENCE
    occurrence = await repo.get_occurrence(results[0].occurrence_key)
    assert occurrence is not None


@pytest.mark.asyncio
async def test_multiple_candidates_yields_ambiguous_disposition_and_persists_nothing(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    mapping_repo = SqlAlchemyEconomicEventSourceMappingRepository(session)
    schedule_use_case = IngestOfficialCalendarSchedule(repo, mapping_repo)
    release_use_case = IngestOfficialCalendarRelease(repo, mapping_repo)

    # Two DIFFERENT schedule-sourced occurrences that both happen to be
    # scheduled on the same calendar date -- an unresolvable ambiguity
    # for date-only correlation.
    schedule_one = _schedule_observation(
        "sched_ambiguous_1", ("CAD_POLICY_RATE_DECISION",), date(2026, 11, 4), _ts(2026, 9, 1)
    )
    schedule_two = _schedule_observation(
        "sched_ambiguous_2", ("CAD_POLICY_RATE_DECISION",), date(2026, 11, 4), _ts(2026, 9, 1)
    )
    await schedule_use_case((schedule_one,))
    await schedule_use_case((schedule_two,))

    release_observation = _release_observation(
        "rel_ambiguous", ("CAD_POLICY_RATE_DECISION",), date(2026, 11, 4), _ts(2026, 11, 4, 9, 50)
    )
    results = await release_use_case((release_observation,))

    assert results[0].disposition is ReleaseIngestionDisposition.AMBIGUOUS_CORRELATION
    assert results[0].occurrence_key == ""
    # Nothing was persisted for this ambiguous attempt.
    stored = await mapping_repo.get_occurrence_key(
        _SOURCE, "rel_ambiguous", "CAD_POLICY_RATE_DECISION"
    )
    assert stored is None
    all_release_vintages_exist: list[EconomicEventReleaseVintage] = []
    for occurrence in await repo.list_occurrences_for_indicator("CAD_POLICY_RATE_DECISION"):
        all_release_vintages_exist.extend(
            await repo.list_all_release_vintages(occurrence.occurrence_key)
        )
    assert all_release_vintages_exist == []


@pytest.mark.asyncio
async def test_unmapped_release_indicator_is_reported(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    mapping_repo = SqlAlchemyEconomicEventSourceMappingRepository(session)
    use_case = IngestOfficialCalendarRelease(repo, mapping_repo)
    observation = _release_observation(
        "rel4", ("SOME_UNKNOWN_INDICATOR",), date(2026, 9, 2), _ts(2026, 9, 2, 9, 50)
    )

    results = await use_case((observation,))

    assert results[0].disposition is ReleaseIngestionDisposition.UNMAPPED


@pytest.mark.asyncio
async def test_source_published_at_flows_through_ingestion_to_persisted_vintage(
    session: AsyncSession,
) -> None:
    # FX-52AH.1: proves the full pipeline, not just the repository layer
    # in isolation -- FX-52AH introduced source_published_at on the raw
    # observation but the use case never carried it into the persisted
    # vintage at all, so it was computed by every real adapter and then
    # silently discarded on every real poll.
    repo = SqlAlchemyEconomicEventRepository(session)
    mapping_repo = SqlAlchemyEconomicEventSourceMappingRepository(session)
    use_case = IngestOfficialCalendarRelease(repo, mapping_repo)
    published_at = _ts(2026, 9, 2, 9, 47)
    observation = _release_observation(
        "rel5",
        ("CAD_POLICY_RATE_DECISION",),
        date(2026, 9, 2),
        _ts(2026, 9, 2, 9, 50),
        released_time=None,
        source_published_at=published_at,
    )

    results = await use_case((observation,))

    release = await repo.release_as_of(results[0].occurrence_key, _ts(2026, 9, 2, 10, 0))
    assert release is not None
    assert release.source_published_at == published_at
    assert release.released_time is None
    assert release.source_published_at != release.availability
