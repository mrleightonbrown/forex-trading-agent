"""FX-51: `SqlAlchemyEconomicEventRepository` round-trip and point-in-time
query tests against live Postgres.

Requires a live Postgres with the FX-51 migration applied — run
`docker compose up -d db && uv run alembic upgrade head` first.
"""

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, time
from decimal import Decimal

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
from forex_agent.infrastructure.db.models.economic_event_schedule_vintage import (
    EconomicEventScheduleVintageRow,
)
from forex_agent.infrastructure.db.session import get_engine

# An indicator key unlikely to ever be real, to keep test rows unambiguous.
TEST_INDICATOR_KEY = "__test_economic_indicator__"


def _ts(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
) -> UtcTimestamp:
    return UtcTimestamp(datetime(year, month, day, hour, minute, second, tzinfo=UTC))


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    async with session_factory() as db_session:
        yield db_session

    async with session_factory() as cleanup_session:
        await cleanup_session.execute(
            delete(EconomicEventScheduleVintageRow).where(
                EconomicEventScheduleVintageRow.indicator_key == TEST_INDICATOR_KEY
            )
        )
        await cleanup_session.execute(
            delete(EconomicEventConsensusVintageRow).where(
                EconomicEventConsensusVintageRow.indicator_key == TEST_INDICATOR_KEY
            )
        )
        await cleanup_session.execute(
            delete(EconomicEventActualValueVintageRow).where(
                EconomicEventActualValueVintageRow.indicator_key == TEST_INDICATOR_KEY
            )
        )
        await cleanup_session.execute(
            delete(EconomicEventOccurrenceRow).where(
                EconomicEventOccurrenceRow.indicator_key == TEST_INDICATOR_KEY
            )
        )
        await cleanup_session.commit()


def _occurrence(
    reference_period: UtcTimestamp, group: str | None = None
) -> EconomicEventOccurrence:
    return EconomicEventOccurrence(
        indicator_key=TEST_INDICATOR_KEY,
        reference_period=reference_period,
        release_group_key=group,
    )


def _schedule(
    reference_period: UtcTimestamp,
    revision_sequence: int,
    scheduled_date: date,
    availability: UtcTimestamp | None,
    status: EconomicEventStatus = EconomicEventStatus.SCHEDULED,
    scheduled_time: time | None = None,
    schedule_timezone: str = "UTC",
    confidence: AvailabilityConfidence = AvailabilityConfidence.VERIFIED,
) -> EconomicEventScheduleVintage:
    return EconomicEventScheduleVintage(
        indicator_key=TEST_INDICATOR_KEY,
        reference_period=reference_period,
        revision_sequence=revision_sequence,
        scheduled_date=scheduled_date,
        scheduled_time=scheduled_time,
        schedule_timezone=schedule_timezone,
        status=status,
        availability=availability,
        availability_confidence=confidence,
        source="test_source",
    )


def _consensus(
    reference_period: UtcTimestamp,
    revision_sequence: int,
    value: Decimal,
    availability: UtcTimestamp | None,
    confidence: AvailabilityConfidence = AvailabilityConfidence.VERIFIED,
) -> EconomicEventConsensusVintage:
    return EconomicEventConsensusVintage(
        indicator_key=TEST_INDICATOR_KEY,
        reference_period=reference_period,
        revision_sequence=revision_sequence,
        consensus_value=value,
        availability=availability,
        availability_confidence=confidence,
        source="test_source",
    )


def _actual(
    reference_period: UtcTimestamp,
    revision_sequence: int,
    value: Decimal,
    availability: UtcTimestamp | None,
    confidence: AvailabilityConfidence = AvailabilityConfidence.VERIFIED,
) -> EconomicEventActualValueVintage:
    return EconomicEventActualValueVintage(
        indicator_key=TEST_INDICATOR_KEY,
        reference_period=reference_period,
        revision_sequence=revision_sequence,
        actual_value=value,
        availability=availability,
        availability_confidence=confidence,
        source="test_source",
    )


# ---------------------------------------------------------------------------
# A. Schedule history / idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_occurrence_add_and_get_round_trips(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    period = _ts(2026, 8, 1)
    occurrence = _occurrence(period, group="NFP_AUG_2026")

    outcome = await repo.add_occurrence(occurrence)
    assert outcome is VintageWriteOutcome.INSERTED

    fetched = await repo.get_occurrence(TEST_INDICATOR_KEY, period)
    assert fetched == occurrence


@pytest.mark.asyncio
async def test_add_occurrence_is_idempotent_on_exact_retry(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    period = _ts(2026, 8, 1)
    occurrence = _occurrence(period)

    first = await repo.add_occurrence(occurrence)
    second = await repo.add_occurrence(occurrence)

    assert first is VintageWriteOutcome.INSERTED
    assert second is VintageWriteOutcome.ALREADY_PRESENT


@pytest.mark.asyncio
async def test_add_occurrence_conflicting_group_key_raises(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    period = _ts(2026, 8, 1)
    original = _occurrence(period, group="GROUP_A")
    conflicting = _occurrence(period, group="GROUP_B")
    await repo.add_occurrence(original)

    with pytest.raises(EconomicEventOccurrenceConflictError):
        await repo.add_occurrence(conflicting)


@pytest.mark.asyncio
async def test_schedule_reschedule_history_is_preserved_worked_example_a(
    session: AsyncSession,
) -> None:
    # FX-51 Section 14 worked example A: a reschedule must not erase what
    # the system knew before the reschedule was known.
    repo = SqlAlchemyEconomicEventRepository(session)
    period = _ts(2026, 10, 1)
    await repo.add_occurrence(_occurrence(period))

    initial = _schedule(period, 0, date(2026, 10, 2), _ts(2026, 9, 1))
    rescheduled = _schedule(period, 1, date(2026, 10, 5), _ts(2026, 9, 20))
    await repo.add_schedule_vintage(initial)
    await repo.add_schedule_vintage(rescheduled)

    before_reschedule_known = await repo.schedule_as_of(
        TEST_INDICATOR_KEY, period, _ts(2026, 9, 10)
    )
    assert before_reschedule_known is not None
    assert before_reschedule_known.scheduled_date == date(2026, 10, 2)

    after_reschedule_known = await repo.schedule_as_of(TEST_INDICATOR_KEY, period, _ts(2026, 9, 25))
    assert after_reschedule_known is not None
    assert after_reschedule_known.scheduled_date == date(2026, 10, 5)

    all_vintages = await repo.list_all_schedule_vintages(TEST_INDICATOR_KEY, period)
    assert len(all_vintages) == 2


@pytest.mark.asyncio
async def test_add_schedule_vintage_is_idempotent_and_conflicts_on_mismatch(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    period = _ts(2026, 10, 1)
    await repo.add_occurrence(_occurrence(period))
    vintage = _schedule(period, 0, date(2026, 10, 2), _ts(2026, 9, 1))

    first = await repo.add_schedule_vintage(vintage)
    second = await repo.add_schedule_vintage(vintage)
    assert first is VintageWriteOutcome.INSERTED
    assert second is VintageWriteOutcome.ALREADY_PRESENT

    conflicting = _schedule(period, 0, date(2026, 10, 3), _ts(2026, 9, 1))
    with pytest.raises(EconomicEventVintageConflictError):
        await repo.add_schedule_vintage(conflicting)


@pytest.mark.asyncio
async def test_schedule_vintage_requires_existing_occurrence(session: AsyncSession) -> None:
    # No FK-satisfying occurrence exists for this reference_period -- the
    # database's own composite FOREIGN KEY must reject the write.
    repo = SqlAlchemyEconomicEventRepository(session)
    period = _ts(2026, 11, 1)
    vintage = _schedule(period, 0, date(2026, 11, 2), _ts(2026, 10, 1))

    with pytest.raises(Exception):  # noqa: B017 -- real IntegrityError from the DB driver
        await repo.add_schedule_vintage(vintage)
    await session.rollback()


# ---------------------------------------------------------------------------
# B/C. Consensus revision -- worked example B
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consensus_revision_worked_example_b(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    period = _ts(2026, 9, 1)
    await repo.add_occurrence(_occurrence(period))

    early = _consensus(period, 0, Decimal("3.1"), _ts(2026, 8, 20))
    revised = _consensus(period, 1, Decimal("3.3"), _ts(2026, 8, 30))
    await repo.add_consensus_vintage(early)
    await repo.add_consensus_vintage(revised)

    before_revision = await repo.consensus_as_of(TEST_INDICATOR_KEY, period, _ts(2026, 8, 25))
    assert before_revision is not None
    assert before_revision.consensus_value == Decimal("3.1")

    after_revision = await repo.consensus_as_of(TEST_INDICATOR_KEY, period, _ts(2026, 9, 1))
    assert after_revision is not None
    assert after_revision.consensus_value == Decimal("3.3")


# ---------------------------------------------------------------------------
# D. Actual value revision, first-release recoverable -- worked example C
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_actual_value_revision_first_release_recoverable_worked_example_c(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    period = _ts(2026, 9, 1)
    await repo.add_occurrence(_occurrence(period))

    release_time = _ts(2026, 9, 4, 13, 30)
    first_release = _actual(period, 0, Decimal("150"), release_time)
    revision_one = _actual(period, 1, Decimal("140"), _ts(2026, 10, 3))
    revision_two = _actual(period, 2, Decimal("137"), _ts(2026, 11, 3))
    await repo.add_actual_value_vintage(first_release)
    await repo.add_actual_value_vintage(revision_one)
    await repo.add_actual_value_vintage(revision_two)

    immediately_after_release = await repo.actual_value_as_of(
        TEST_INDICATOR_KEY, period, _ts(2026, 9, 4, 13, 31)
    )
    assert immediately_after_release is not None
    assert immediately_after_release.actual_value == Decimal("150")

    after_first_revision = await repo.actual_value_as_of(
        TEST_INDICATOR_KEY, period, _ts(2026, 10, 10)
    )
    assert after_first_revision is not None
    assert after_first_revision.actual_value == Decimal("140")

    after_both_revisions = await repo.actual_value_as_of(
        TEST_INDICATOR_KEY, period, _ts(2026, 12, 1)
    )
    assert after_both_revisions is not None
    assert after_both_revisions.actual_value == Decimal("137")

    # The first release must remain recoverable forever, even long after
    # later revisions are also visible.
    first_release_much_later = await repo.first_release_as_of(
        TEST_INDICATOR_KEY, period, _ts(2026, 12, 1)
    )
    assert first_release_much_later is not None
    assert first_release_much_later.actual_value == Decimal("150")
    assert first_release_much_later.revision_sequence == 0


@pytest.mark.asyncio
async def test_actual_value_conflict_on_mismatched_payload(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    period = _ts(2026, 9, 1)
    await repo.add_occurrence(_occurrence(period))
    original = _actual(period, 0, Decimal("150"), _ts(2026, 9, 4))
    await repo.add_actual_value_vintage(original)

    conflicting = _actual(period, 0, Decimal("999"), _ts(2026, 9, 4))
    with pytest.raises(EconomicEventVintageConflictError):
        await repo.add_actual_value_vintage(conflicting)


# ---------------------------------------------------------------------------
# E. Backfill / unknown availability -- worked example D
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_availability_actual_value_is_never_visible_worked_example_d(
    session: AsyncSession,
) -> None:
    # A backfilled actual value whose real-world availability was never
    # established must NOT be treated as known at any as_of, however far
    # in the future -- this is the fail-closed guarantee for UNKNOWN.
    repo = SqlAlchemyEconomicEventRepository(session)
    period = _ts(2020, 1, 1)
    await repo.add_occurrence(_occurrence(period))

    backfilled_unknown = _actual(
        period, 0, Decimal("42"), None, confidence=AvailabilityConfidence.UNKNOWN
    )
    outcome = await repo.add_actual_value_vintage(backfilled_unknown)
    assert outcome is VintageWriteOutcome.INSERTED

    far_future = await repo.actual_value_as_of(TEST_INDICATOR_KEY, period, _ts(2099, 1, 1))
    assert far_future is None

    far_future_first_release = await repo.first_release_as_of(
        TEST_INDICATOR_KEY, period, _ts(2099, 1, 1)
    )
    assert far_future_first_release is None


@pytest.mark.asyncio
async def test_estimated_availability_is_visible_but_distinguishable_from_verified(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    period = _ts(2020, 1, 1)
    await repo.add_occurrence(_occurrence(period))
    estimated = _actual(
        period, 0, Decimal("42"), _ts(2020, 2, 1), confidence=AvailabilityConfidence.ESTIMATED
    )
    await repo.add_actual_value_vintage(estimated)

    result = await repo.actual_value_as_of(TEST_INDICATOR_KEY, period, _ts(2020, 2, 2))
    assert result is not None
    assert result.availability_confidence is AvailabilityConfidence.ESTIMATED


# ---------------------------------------------------------------------------
# F. Datetime / timezone handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_schedule_timezone_and_unknown_time_round_trip(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    period = _ts(2026, 12, 1)
    await repo.add_occurrence(_occurrence(period))
    vintage = _schedule(
        period,
        0,
        date(2026, 12, 5),
        _ts(2026, 11, 1),
        scheduled_time=None,
        schedule_timezone="America/New_York",
    )
    await repo.add_schedule_vintage(vintage)

    result = await repo.schedule_as_of(TEST_INDICATOR_KEY, period, _ts(2026, 11, 15))
    assert result is not None
    assert result.scheduled_time is None
    assert result.schedule_timezone == "America/New_York"


@pytest.mark.asyncio
async def test_schedule_time_when_known_round_trips_exactly(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    period = _ts(2026, 12, 1)
    await repo.add_occurrence(_occurrence(period))
    vintage = _schedule(
        period,
        0,
        date(2026, 12, 5),
        _ts(2026, 11, 1),
        scheduled_time=time(8, 30, 0),
        schedule_timezone="America/New_York",
    )
    await repo.add_schedule_vintage(vintage)

    result = await repo.schedule_as_of(TEST_INDICATOR_KEY, period, _ts(2026, 11, 15))
    assert result is not None
    assert result.scheduled_time == time(8, 30, 0)


# ---------------------------------------------------------------------------
# G. Identity / idempotency (already partly covered above) + Decimal fidelity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decimal_fidelity_round_trips_for_consensus_and_actual(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    period = _ts(2026, 9, 1)
    await repo.add_occurrence(_occurrence(period))
    precise = Decimal("3.123456789")
    await repo.add_consensus_vintage(_consensus(period, 0, precise, _ts(2026, 8, 1)))
    await repo.add_actual_value_vintage(_actual(period, 0, precise, _ts(2026, 9, 4)))

    consensus = await repo.consensus_as_of(TEST_INDICATOR_KEY, period, _ts(2026, 8, 15))
    actual = await repo.actual_value_as_of(TEST_INDICATOR_KEY, period, _ts(2026, 9, 5))
    assert consensus is not None
    assert actual is not None
    assert consensus.consensus_value == precise
    assert actual.actual_value == precise
    assert isinstance(consensus.consensus_value, Decimal)
    assert isinstance(actual.actual_value, Decimal)


# ---------------------------------------------------------------------------
# I. Release grouping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_release_group_key_links_related_occurrences_without_forcing_shared_timestamp(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    period = _ts(2026, 9, 4)
    headline = _occurrence(period, group="EMPLOYMENT_SITUATION_SEP_2026")
    unemployment = EconomicEventOccurrence(
        indicator_key=TEST_INDICATOR_KEY + "_unemployment",
        reference_period=period,
        release_group_key="EMPLOYMENT_SITUATION_SEP_2026",
    )
    await repo.add_occurrence(headline)
    # Only clean up the second, differently-keyed indicator explicitly --
    # the fixture's teardown filters strictly on TEST_INDICATOR_KEY.
    try:
        await repo.add_occurrence(unemployment)
        fetched_headline = await repo.get_occurrence(TEST_INDICATOR_KEY, period)
        fetched_unemployment = await repo.get_occurrence(
            TEST_INDICATOR_KEY + "_unemployment", period
        )
        assert fetched_headline is not None
        assert fetched_unemployment is not None
        assert fetched_headline.release_group_key == fetched_unemployment.release_group_key
        assert fetched_headline.indicator_key != fetched_unemployment.indicator_key
    finally:
        await session.execute(
            delete(EconomicEventOccurrenceRow).where(
                EconomicEventOccurrenceRow.indicator_key == TEST_INDICATOR_KEY + "_unemployment"
            )
        )
        await session.commit()


# ---------------------------------------------------------------------------
# J. known_events_in_window
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_known_events_in_window_reflects_rescheduled_date_and_excludes_out_of_window(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    in_window_period = _ts(2026, 10, 1)
    out_of_window_period = _ts(2026, 10, 2)
    await repo.add_occurrence(_occurrence(in_window_period))
    await repo.add_occurrence(_occurrence(out_of_window_period))

    await repo.add_schedule_vintage(
        _schedule(in_window_period, 0, date(2026, 10, 2), _ts(2026, 9, 1))
    )
    await repo.add_schedule_vintage(
        _schedule(in_window_period, 1, date(2026, 10, 5), _ts(2026, 9, 20))
    )
    await repo.add_schedule_vintage(
        _schedule(out_of_window_period, 0, date(2026, 11, 15), _ts(2026, 9, 1))
    )

    results = await repo.known_events_in_window(
        _ts(2026, 10, 1), _ts(2026, 10, 31), _ts(2026, 9, 25)
    )

    matching = [r for r in results if r[0].indicator_key == TEST_INDICATOR_KEY]
    assert len(matching) == 1
    occurrence, schedule = matching[0]
    assert occurrence.reference_period == in_window_period
    assert schedule.scheduled_date == date(2026, 10, 5)


@pytest.mark.asyncio
async def test_known_events_in_window_excludes_unknown_availability_schedule(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    period = _ts(2026, 10, 1)
    await repo.add_occurrence(_occurrence(period))
    await repo.add_schedule_vintage(
        _schedule(
            period,
            0,
            date(2026, 10, 2),
            None,
            confidence=AvailabilityConfidence.UNKNOWN,
        )
    )

    results = await repo.known_events_in_window(
        _ts(2026, 10, 1), _ts(2026, 10, 31), _ts(2099, 1, 1)
    )

    matching = [r for r in results if r[0].indicator_key == TEST_INDICATOR_KEY]
    assert matching == []
