"""FX-51/FX-51H: `SqlAlchemyEconomicEventRepository` round-trip and
point-in-time query tests against live Postgres.

Requires a live Postgres with the FX-51H migration applied — run
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
from forex_agent.domain.economic_event_release_vintage import EconomicEventReleaseVintage
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
from forex_agent.infrastructure.db.models.economic_event_release_vintage import (
    EconomicEventReleaseVintageRow,
)
from forex_agent.infrastructure.db.models.economic_event_schedule_vintage import (
    EconomicEventScheduleVintageRow,
)
from forex_agent.infrastructure.db.session import get_engine

# An indicator key unlikely to ever be real, to keep test rows unambiguous.
TEST_INDICATOR_KEY = "__test_economic_indicator__"
TEST_OCCURRENCE_PREFIX = "__test_occ__"


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
        for row_type in (
            EconomicEventScheduleVintageRow,
            EconomicEventConsensusVintageRow,
            EconomicEventActualValueVintageRow,
            EconomicEventReleaseVintageRow,
        ):
            await cleanup_session.execute(
                delete(row_type).where(row_type.occurrence_key.startswith(TEST_OCCURRENCE_PREFIX))
            )
        await cleanup_session.execute(
            delete(EconomicEventOccurrenceRow).where(
                EconomicEventOccurrenceRow.occurrence_key.startswith(TEST_OCCURRENCE_PREFIX)
            )
        )
        await cleanup_session.commit()


def _occurrence(
    occurrence_key: str,
    reference_period: UtcTimestamp | None = None,
    group: str | None = None,
    indicator_key: str = TEST_INDICATOR_KEY,
) -> EconomicEventOccurrence:
    return EconomicEventOccurrence(
        occurrence_key=occurrence_key,
        indicator_key=indicator_key,
        reference_period=reference_period,
        release_group_key=group,
    )


def _schedule(
    occurrence_key: str,
    revision_sequence: int,
    scheduled_date: date,
    availability: UtcTimestamp | None,
    status: EconomicEventStatus = EconomicEventStatus.SCHEDULED,
    scheduled_time: time | None = None,
    schedule_timezone: str = "UTC",
    confidence: AvailabilityConfidence = AvailabilityConfidence.VERIFIED,
) -> EconomicEventScheduleVintage:
    return EconomicEventScheduleVintage(
        occurrence_key=occurrence_key,
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
    occurrence_key: str,
    revision_sequence: int,
    value: Decimal,
    availability: UtcTimestamp | None,
    confidence: AvailabilityConfidence = AvailabilityConfidence.VERIFIED,
) -> EconomicEventConsensusVintage:
    return EconomicEventConsensusVintage(
        occurrence_key=occurrence_key,
        revision_sequence=revision_sequence,
        consensus_value=value,
        availability=availability,
        availability_confidence=confidence,
        source="test_source",
    )


def _actual(
    occurrence_key: str,
    revision_sequence: int,
    value: Decimal,
    availability: UtcTimestamp | None,
    confidence: AvailabilityConfidence = AvailabilityConfidence.VERIFIED,
) -> EconomicEventActualValueVintage:
    return EconomicEventActualValueVintage(
        occurrence_key=occurrence_key,
        revision_sequence=revision_sequence,
        actual_value=value,
        availability=availability,
        availability_confidence=confidence,
        source="test_source",
    )


def _release(
    occurrence_key: str,
    revision_sequence: int,
    released_date: date,
    released_time: time | None,
    availability: UtcTimestamp | None,
    released_timezone: str = "UTC",
    confidence: AvailabilityConfidence = AvailabilityConfidence.VERIFIED,
) -> EconomicEventReleaseVintage:
    return EconomicEventReleaseVintage(
        occurrence_key=occurrence_key,
        revision_sequence=revision_sequence,
        released_date=released_date,
        released_time=released_time,
        released_timezone=released_timezone,
        availability=availability,
        availability_confidence=confidence,
        source="test_source",
    )


# ---------------------------------------------------------------------------
# A. Schedule history / idempotency / identity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_occurrence_add_and_get_round_trips(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    key = f"{TEST_OCCURRENCE_PREFIX}A1"
    occurrence = _occurrence(key, reference_period=_ts(2026, 8, 1), group="NFP_AUG_2026")

    outcome = await repo.add_occurrence(occurrence)
    assert outcome is VintageWriteOutcome.INSERTED

    fetched = await repo.get_occurrence(key)
    assert fetched == occurrence


@pytest.mark.asyncio
async def test_add_occurrence_is_idempotent_on_exact_retry(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    key = f"{TEST_OCCURRENCE_PREFIX}A2"
    occurrence = _occurrence(key, reference_period=_ts(2026, 8, 1))

    first = await repo.add_occurrence(occurrence)
    second = await repo.add_occurrence(occurrence)

    assert first is VintageWriteOutcome.INSERTED
    assert second is VintageWriteOutcome.ALREADY_PRESENT


@pytest.mark.asyncio
async def test_add_occurrence_conflicting_content_raises(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    key = f"{TEST_OCCURRENCE_PREFIX}A3"
    original = _occurrence(key, reference_period=_ts(2026, 8, 1), group="GROUP_A")
    conflicting = _occurrence(key, reference_period=_ts(2026, 8, 1), group="GROUP_B")
    await repo.add_occurrence(original)

    with pytest.raises(EconomicEventOccurrenceConflictError):
        await repo.add_occurrence(conflicting)


@pytest.mark.asyncio
async def test_periodic_occurrence_has_reference_period(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    key = f"{TEST_OCCURRENCE_PREFIX}A4_PERIODIC"
    occurrence = _occurrence(key, reference_period=_ts(2026, 8, 1))
    await repo.add_occurrence(occurrence)

    fetched = await repo.get_occurrence(key)
    assert fetched is not None
    assert fetched.reference_period == _ts(2026, 8, 1)


@pytest.mark.asyncio
async def test_qualitative_irregular_occurrence_has_no_reference_period(
    session: AsyncSession,
) -> None:
    # A press conference is not "for" a calendar period at all.
    repo = SqlAlchemyEconomicEventRepository(session)
    key = f"{TEST_OCCURRENCE_PREFIX}A5_FOMC"
    occurrence = _occurrence(key, reference_period=None, indicator_key="FOMC_PRESS_CONFERENCE")
    await repo.add_occurrence(occurrence)

    fetched = await repo.get_occurrence(key)
    assert fetched is not None
    assert fetched.reference_period is None


@pytest.mark.asyncio
async def test_schedule_reschedule_history_is_preserved_worked_example_a(
    session: AsyncSession,
) -> None:
    # FX-51 Section 14 worked example A: a reschedule must not erase what
    # the system knew before the reschedule was known, and (FX-51H) must
    # NOT change the occurrence's own identity.
    repo = SqlAlchemyEconomicEventRepository(session)
    key = f"{TEST_OCCURRENCE_PREFIX}A6"
    await repo.add_occurrence(_occurrence(key, reference_period=_ts(2026, 10, 1)))

    initial = _schedule(key, 0, date(2026, 10, 2), _ts(2026, 9, 1))
    rescheduled = _schedule(key, 1, date(2026, 10, 5), _ts(2026, 9, 20))
    await repo.add_schedule_vintage(initial)
    await repo.add_schedule_vintage(rescheduled)

    before_reschedule_known = await repo.schedule_as_of(key, _ts(2026, 9, 10))
    assert before_reschedule_known is not None
    assert before_reschedule_known.scheduled_date == date(2026, 10, 2)
    assert before_reschedule_known.occurrence_key == key

    after_reschedule_known = await repo.schedule_as_of(key, _ts(2026, 9, 25))
    assert after_reschedule_known is not None
    assert after_reschedule_known.scheduled_date == date(2026, 10, 5)
    assert after_reschedule_known.occurrence_key == key  # identity unchanged

    all_vintages = await repo.list_all_schedule_vintages(key)
    assert len(all_vintages) == 2
    # Same occurrence identity retrieves the SAME occurrence row too.
    assert await repo.get_occurrence(key) is not None


@pytest.mark.asyncio
async def test_add_schedule_vintage_is_idempotent_and_conflicts_on_mismatch(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    key = f"{TEST_OCCURRENCE_PREFIX}A7"
    await repo.add_occurrence(_occurrence(key, reference_period=_ts(2026, 10, 1)))
    vintage = _schedule(key, 0, date(2026, 10, 2), _ts(2026, 9, 1))

    first = await repo.add_schedule_vintage(vintage)
    second = await repo.add_schedule_vintage(vintage)
    assert first is VintageWriteOutcome.INSERTED
    assert second is VintageWriteOutcome.ALREADY_PRESENT

    conflicting = _schedule(key, 0, date(2026, 10, 3), _ts(2026, 9, 1))
    with pytest.raises(EconomicEventVintageConflictError):
        await repo.add_schedule_vintage(conflicting)


@pytest.mark.asyncio
async def test_schedule_vintage_requires_existing_occurrence(session: AsyncSession) -> None:
    # No FK-satisfying occurrence exists for this occurrence_key -- the
    # database's own FOREIGN KEY must reject the write.
    repo = SqlAlchemyEconomicEventRepository(session)
    key = f"{TEST_OCCURRENCE_PREFIX}A8_NONEXISTENT"
    vintage = _schedule(key, 0, date(2026, 11, 2), _ts(2026, 10, 1))

    with pytest.raises(Exception):  # noqa: B017 -- real IntegrityError from the DB driver
        await repo.add_schedule_vintage(vintage)
    await session.rollback()


# ---------------------------------------------------------------------------
# B/C. Consensus revision -- worked example B
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consensus_revision_worked_example_b(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    key = f"{TEST_OCCURRENCE_PREFIX}B1"
    await repo.add_occurrence(_occurrence(key, reference_period=_ts(2026, 9, 1)))

    early = _consensus(key, 0, Decimal("3.1"), _ts(2026, 8, 20))
    revised = _consensus(key, 1, Decimal("3.3"), _ts(2026, 8, 30))
    await repo.add_consensus_vintage(early)
    await repo.add_consensus_vintage(revised)

    before_revision = await repo.consensus_as_of(key, _ts(2026, 8, 25))
    assert before_revision is not None
    assert before_revision.consensus_value == Decimal("3.1")

    after_revision = await repo.consensus_as_of(key, _ts(2026, 9, 1))
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
    key = f"{TEST_OCCURRENCE_PREFIX}D1"
    await repo.add_occurrence(_occurrence(key, reference_period=_ts(2026, 9, 1)))

    release_time = _ts(2026, 9, 4, 13, 30)
    first_release = _actual(key, 0, Decimal("150"), release_time)
    revision_one = _actual(key, 1, Decimal("140"), _ts(2026, 10, 3))
    revision_two = _actual(key, 2, Decimal("137"), _ts(2026, 11, 3))
    await repo.add_actual_value_vintage(first_release)
    await repo.add_actual_value_vintage(revision_one)
    await repo.add_actual_value_vintage(revision_two)

    immediately_after_release = await repo.actual_value_as_of(key, _ts(2026, 9, 4, 13, 31))
    assert immediately_after_release is not None
    assert immediately_after_release.actual_value == Decimal("150")

    after_first_revision = await repo.actual_value_as_of(key, _ts(2026, 10, 10))
    assert after_first_revision is not None
    assert after_first_revision.actual_value == Decimal("140")

    after_both_revisions = await repo.actual_value_as_of(key, _ts(2026, 12, 1))
    assert after_both_revisions is not None
    assert after_both_revisions.actual_value == Decimal("137")

    # The first release must remain recoverable forever, even long after
    # later revisions are also visible.
    first_release_much_later = await repo.first_release_as_of(key, _ts(2026, 12, 1))
    assert first_release_much_later is not None
    assert first_release_much_later.actual_value == Decimal("150")
    assert first_release_much_later.revision_sequence == 0


@pytest.mark.asyncio
async def test_actual_value_conflict_on_mismatched_payload(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    key = f"{TEST_OCCURRENCE_PREFIX}D2"
    await repo.add_occurrence(_occurrence(key, reference_period=_ts(2026, 9, 1)))
    original = _actual(key, 0, Decimal("150"), _ts(2026, 9, 4))
    await repo.add_actual_value_vintage(original)

    conflicting = _actual(key, 0, Decimal("999"), _ts(2026, 9, 4))
    with pytest.raises(EconomicEventVintageConflictError):
        await repo.add_actual_value_vintage(conflicting)


# ---------------------------------------------------------------------------
# E. Backfill / unknown availability -- worked example D
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_availability_actual_value_is_never_visible_worked_example_d(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    key = f"{TEST_OCCURRENCE_PREFIX}E1"
    await repo.add_occurrence(_occurrence(key, reference_period=_ts(2020, 1, 1)))

    backfilled_unknown = _actual(
        key, 0, Decimal("42"), None, confidence=AvailabilityConfidence.UNKNOWN
    )
    outcome = await repo.add_actual_value_vintage(backfilled_unknown)
    assert outcome is VintageWriteOutcome.INSERTED

    far_future = await repo.actual_value_as_of(key, _ts(2099, 1, 1))
    assert far_future is None

    far_future_first_release = await repo.first_release_as_of(key, _ts(2099, 1, 1))
    assert far_future_first_release is None


@pytest.mark.asyncio
async def test_estimated_availability_is_visible_but_distinguishable_from_verified(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    key = f"{TEST_OCCURRENCE_PREFIX}E2"
    await repo.add_occurrence(_occurrence(key, reference_period=_ts(2020, 1, 1)))
    estimated = _actual(
        key, 0, Decimal("42"), _ts(2020, 2, 1), confidence=AvailabilityConfidence.ESTIMATED
    )
    await repo.add_actual_value_vintage(estimated)

    result = await repo.actual_value_as_of(key, _ts(2020, 2, 2))
    assert result is not None
    assert result.availability_confidence is AvailabilityConfidence.ESTIMATED


# ---------------------------------------------------------------------------
# Release vintages (FX-51H)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_release_time_independent_of_availability_time(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    key = f"{TEST_OCCURRENCE_PREFIX}REL1"
    await repo.add_occurrence(_occurrence(key, reference_period=_ts(2026, 9, 4)))

    release = _release(
        key, 0, date(2026, 9, 4), time(13, 30), _ts(2026, 9, 6, 9, 0), released_timezone="UTC"
    )
    outcome = await repo.add_release_vintage(release)
    assert outcome is VintageWriteOutcome.INSERTED

    before_availability = await repo.release_as_of(key, _ts(2026, 9, 5))
    after_availability = await repo.release_as_of(key, _ts(2026, 9, 6, 10, 0))
    assert before_availability is None
    assert after_availability is not None
    assert after_availability.released_date == date(2026, 9, 4)
    assert after_availability.released_time == time(13, 30)


@pytest.mark.asyncio
async def test_qualitative_event_release_without_actual_value(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    key = f"{TEST_OCCURRENCE_PREFIX}REL2_FOMC"
    await repo.add_occurrence(
        _occurrence(key, reference_period=None, indicator_key="FOMC_PRESS_CONFERENCE")
    )

    release = _release(key, 0, date(2026, 9, 17), time(14, 0), _ts(2026, 9, 17, 18, 5))
    await repo.add_release_vintage(release)

    result = await repo.release_as_of(key, _ts(2026, 9, 18))
    assert result is not None
    assert result.released_date == date(2026, 9, 17)
    # No actual-value vintage exists for this occurrence at all.
    actual = await repo.actual_value_as_of(key, _ts(2026, 9, 18))
    assert actual is None
    all_actuals = await repo.list_all_actual_value_vintages(key)
    assert all_actuals == ()


@pytest.mark.asyncio
async def test_release_unknown_time_remains_time_unknown(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    key = f"{TEST_OCCURRENCE_PREFIX}REL3"
    await repo.add_occurrence(_occurrence(key, reference_period=_ts(2026, 9, 4)))
    release = _release(key, 0, date(2026, 9, 4), None, _ts(2026, 9, 5))
    await repo.add_release_vintage(release)

    result = await repo.release_as_of(key, _ts(2026, 9, 6))
    assert result is not None
    assert result.released_time is None


@pytest.mark.asyncio
async def test_release_after_a_reschedule_is_recoverable(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    key = f"{TEST_OCCURRENCE_PREFIX}REL4"
    await repo.add_occurrence(_occurrence(key, reference_period=_ts(2026, 10, 1)))
    await repo.add_schedule_vintage(_schedule(key, 0, date(2026, 10, 2), _ts(2026, 9, 1)))
    await repo.add_schedule_vintage(_schedule(key, 1, date(2026, 10, 5), _ts(2026, 9, 20)))
    release = _release(key, 0, date(2026, 10, 5), time(8, 30), _ts(2026, 10, 5, 8, 35))
    await repo.add_release_vintage(release)

    schedule_state = await repo.schedule_as_of(key, _ts(2026, 10, 6))
    release_state = await repo.release_as_of(key, _ts(2026, 10, 6))
    assert schedule_state is not None and schedule_state.scheduled_date == date(2026, 10, 5)
    assert release_state is not None and release_state.released_date == date(2026, 10, 5)
    assert schedule_state.occurrence_key == release_state.occurrence_key == key


@pytest.mark.asyncio
async def test_release_vintage_conflict_on_mismatched_payload(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    key = f"{TEST_OCCURRENCE_PREFIX}REL5"
    await repo.add_occurrence(_occurrence(key, reference_period=_ts(2026, 9, 4)))
    original = _release(key, 0, date(2026, 9, 4), time(13, 30), _ts(2026, 9, 4, 13, 35))
    await repo.add_release_vintage(original)

    conflicting = _release(key, 0, date(2026, 9, 5), time(13, 30), _ts(2026, 9, 4, 13, 35))
    with pytest.raises(EconomicEventVintageConflictError):
        await repo.add_release_vintage(conflicting)


# ---------------------------------------------------------------------------
# release_group_key NULL -> known enrichment (FX-51H)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_attach_release_group_to_previously_ungrouped_occurrence(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    key = f"{TEST_OCCURRENCE_PREFIX}GRP1"
    await repo.add_occurrence(_occurrence(key, reference_period=_ts(2026, 9, 4), group=None))

    await repo.attach_release_group(key, "EMPLOYMENT_SITUATION_SEP_2026")

    fetched = await repo.get_occurrence(key)
    assert fetched is not None
    assert fetched.release_group_key == "EMPLOYMENT_SITUATION_SEP_2026"


@pytest.mark.asyncio
async def test_attach_release_group_is_idempotent_for_the_same_value(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    key = f"{TEST_OCCURRENCE_PREFIX}GRP2"
    await repo.add_occurrence(_occurrence(key, reference_period=_ts(2026, 9, 4), group=None))

    await repo.attach_release_group(key, "GROUP_X")
    await repo.attach_release_group(key, "GROUP_X")  # must not raise

    fetched = await repo.get_occurrence(key)
    assert fetched is not None
    assert fetched.release_group_key == "GROUP_X"


@pytest.mark.asyncio
async def test_attach_release_group_conflicts_on_a_different_value(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    key = f"{TEST_OCCURRENCE_PREFIX}GRP3"
    await repo.add_occurrence(_occurrence(key, reference_period=_ts(2026, 9, 4), group="GROUP_A"))

    with pytest.raises(ValueError, match="already has release_group_key"):
        await repo.attach_release_group(key, "GROUP_B")

    fetched = await repo.get_occurrence(key)
    assert fetched is not None
    assert fetched.release_group_key == "GROUP_A"  # untouched


@pytest.mark.asyncio
async def test_attach_release_group_rejects_missing_occurrence(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    key = f"{TEST_OCCURRENCE_PREFIX}GRP4_MISSING"

    with pytest.raises(ValueError, match="no occurrence exists"):
        await repo.attach_release_group(key, "GROUP_X")


# ---------------------------------------------------------------------------
# Decimal fidelity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decimal_fidelity_round_trips_for_consensus_and_actual(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    key = f"{TEST_OCCURRENCE_PREFIX}DEC1"
    await repo.add_occurrence(_occurrence(key, reference_period=_ts(2026, 9, 1)))
    precise = Decimal("3.123456789")
    await repo.add_consensus_vintage(_consensus(key, 0, precise, _ts(2026, 8, 1)))
    await repo.add_actual_value_vintage(_actual(key, 0, precise, _ts(2026, 9, 4)))

    consensus = await repo.consensus_as_of(key, _ts(2026, 8, 15))
    actual = await repo.actual_value_as_of(key, _ts(2026, 9, 5))
    assert consensus is not None
    assert actual is not None
    assert consensus.consensus_value == precise
    assert actual.actual_value == precise
    assert isinstance(consensus.consensus_value, Decimal)
    assert isinstance(actual.actual_value, Decimal)


# ---------------------------------------------------------------------------
# Release grouping (structural, set at creation)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_release_group_key_links_related_occurrences_without_forcing_shared_timestamp(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    period = _ts(2026, 9, 4)
    headline_key = f"{TEST_OCCURRENCE_PREFIX}GROUPED_HEADLINE"
    unemployment_key = f"{TEST_OCCURRENCE_PREFIX}GROUPED_UNEMPLOYMENT"
    headline = _occurrence(headline_key, reference_period=period, group="EMPLOYMENT_SEP_2026")
    unemployment = _occurrence(
        unemployment_key,
        reference_period=period,
        group="EMPLOYMENT_SEP_2026",
        indicator_key=TEST_INDICATOR_KEY + "_unemployment",
    )
    await repo.add_occurrence(headline)
    await repo.add_occurrence(unemployment)

    fetched_headline = await repo.get_occurrence(headline_key)
    fetched_unemployment = await repo.get_occurrence(unemployment_key)
    assert fetched_headline is not None
    assert fetched_unemployment is not None
    assert fetched_headline.release_group_key == fetched_unemployment.release_group_key
    assert fetched_headline.indicator_key != fetched_unemployment.indicator_key
    assert fetched_headline.occurrence_key != fetched_unemployment.occurrence_key


# ---------------------------------------------------------------------------
# known_events_in_window (FX-51H: true timezone-resolved instants)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_known_events_in_window_reflects_rescheduled_date_and_excludes_out_of_window(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    in_window_key = f"{TEST_OCCURRENCE_PREFIX}WIN1_IN"
    out_of_window_key = f"{TEST_OCCURRENCE_PREFIX}WIN1_OUT"
    await repo.add_occurrence(_occurrence(in_window_key, reference_period=_ts(2026, 10, 1)))
    await repo.add_occurrence(_occurrence(out_of_window_key, reference_period=_ts(2026, 10, 2)))

    await repo.add_schedule_vintage(_schedule(in_window_key, 0, date(2026, 10, 2), _ts(2026, 9, 1)))
    await repo.add_schedule_vintage(
        _schedule(in_window_key, 1, date(2026, 10, 5), _ts(2026, 9, 20))
    )
    await repo.add_schedule_vintage(
        _schedule(out_of_window_key, 0, date(2026, 11, 15), _ts(2026, 9, 1))
    )

    results = await repo.known_events_in_window(
        _ts(2026, 10, 1), _ts(2026, 10, 31), _ts(2026, 9, 25)
    )

    matching = [r for r in results if r[0].occurrence_key.startswith(TEST_OCCURRENCE_PREFIX)]
    assert len(matching) == 1
    occurrence, schedule = matching[0]
    assert occurrence.occurrence_key == in_window_key
    assert schedule.scheduled_date == date(2026, 10, 5)


@pytest.mark.asyncio
async def test_known_events_in_window_excludes_unknown_availability_schedule(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    key = f"{TEST_OCCURRENCE_PREFIX}WIN2"
    await repo.add_occurrence(_occurrence(key, reference_period=_ts(2026, 10, 1)))
    await repo.add_schedule_vintage(
        _schedule(
            key,
            0,
            date(2026, 10, 2),
            None,
            confidence=AvailabilityConfidence.UNKNOWN,
        )
    )

    results = await repo.known_events_in_window(
        _ts(2026, 10, 1), _ts(2026, 10, 31), _ts(2099, 1, 1)
    )

    matching = [r for r in results if r[0].occurrence_key == key]
    assert matching == []


@pytest.mark.asyncio
async def test_known_events_in_window_uses_true_timezone_resolved_instant(
    session: AsyncSession,
) -> None:
    # A late-evening America/New_York schedule whose UTC instant falls on
    # the NEXT calendar day -- FX-51's original naive local-date-vs-UTC-
    # date comparison would have misplaced this; the true instant test
    # must place it correctly on the UTC day it actually resolves to.
    repo = SqlAlchemyEconomicEventRepository(session)
    key = f"{TEST_OCCURRENCE_PREFIX}WIN3_DST"
    await repo.add_occurrence(_occurrence(key, reference_period=_ts(2026, 1, 1)))
    await repo.add_schedule_vintage(
        _schedule(
            key,
            0,
            date(2026, 1, 15),
            _ts(2026, 1, 1),
            scheduled_time=time(23, 0),
            schedule_timezone="America/New_York",
        )
    )
    # 2026-01-15 23:00 America/New_York (EST, UTC-5) == 2026-01-16 04:00 UTC.
    jan_15_window = await repo.known_events_in_window(
        _ts(2026, 1, 15), _ts(2026, 1, 16), _ts(2026, 1, 2)
    )
    jan_16_window = await repo.known_events_in_window(
        _ts(2026, 1, 16), _ts(2026, 1, 17), _ts(2026, 1, 2)
    )

    assert key not in [o.occurrence_key for o, _s in jan_15_window]
    assert key in [o.occurrence_key for o, _s in jan_16_window]


@pytest.mark.asyncio
async def test_known_events_in_window_date_only_schedule_uses_local_day_overlap(
    session: AsyncSession,
) -> None:
    # No instant is fabricated for a date-only/TBD schedule -- membership
    # is decided by whether the resolved LOCAL DAY overlaps the window.
    repo = SqlAlchemyEconomicEventRepository(session)
    key = f"{TEST_OCCURRENCE_PREFIX}WIN4_TBD"
    await repo.add_occurrence(_occurrence(key, reference_period=_ts(2026, 1, 1)))
    await repo.add_schedule_vintage(
        _schedule(
            key,
            0,
            date(2026, 1, 15),
            _ts(2026, 1, 1),
            scheduled_time=None,
            schedule_timezone="America/New_York",
        )
    )
    # Local day 2026-01-15 in America/New_York (EST, UTC-5) spans
    # [2026-01-15 05:00 UTC, 2026-01-16 05:00 UTC).
    overlapping = await repo.known_events_in_window(
        _ts(2026, 1, 16), _ts(2026, 1, 16, 6), _ts(2026, 1, 2)
    )
    non_overlapping = await repo.known_events_in_window(
        _ts(2026, 1, 16, 6), _ts(2026, 1, 17), _ts(2026, 1, 2)
    )

    assert key in [o.occurrence_key for o, _s in overlapping]
    assert key not in [o.occurrence_key for o, _s in non_overlapping]
    result_schedule = next(s for o, s in overlapping if o.occurrence_key == key)
    assert result_schedule.scheduled_time is None  # never fabricated
