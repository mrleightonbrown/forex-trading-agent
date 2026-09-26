"""FX-51/FX-51H: `GetEconomicEventState` use-case tests against
`SqlAlchemyEconomicEventRepository` and live Postgres -- see
tests/integration/test_economic_event_repository.py for the repository's
own, more exhaustive point-in-time tests; this file only exercises the
use case's own orchestration/assembly behaviour.
"""

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.application.use_cases.get_economic_event_state import GetEconomicEventState
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

TEST_OCCURRENCE_PREFIX = "__test_get_event_state__"


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
                delete(row_type).where(row_type.occurrence_key.startswith(TEST_OCCURRENCE_PREFIX))
            )
        await cleanup_session.execute(
            delete(EconomicEventOccurrenceRow).where(
                EconomicEventOccurrenceRow.occurrence_key.startswith(TEST_OCCURRENCE_PREFIX)
            )
        )
        await cleanup_session.commit()


@pytest.mark.asyncio
async def test_returns_none_when_occurrence_does_not_exist(session: AsyncSession) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    use_case = GetEconomicEventState(repo)
    key = f"{TEST_OCCURRENCE_PREFIX}_MISSING"

    result = await use_case(key, _ts(2026, 9, 1))

    assert result is None


@pytest.mark.asyncio
async def test_assembles_schedule_consensus_actual_release_and_first_release(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    use_case = GetEconomicEventState(repo)
    key = f"{TEST_OCCURRENCE_PREFIX}_NFP"
    period = _ts(2026, 9, 4)

    await repo.add_occurrence(
        EconomicEventOccurrence(occurrence_key=key, indicator_key="US_NFP", reference_period=period)
    )
    await repo.add_schedule_vintage(
        EconomicEventScheduleVintage(
            occurrence_key=key,
            revision_sequence=0,
            scheduled_date=date(2026, 9, 4),
            scheduled_time=None,
            schedule_timezone="UTC",
            status=EconomicEventStatus.SCHEDULED,
            availability=_ts(2026, 8, 1),
            availability_confidence=AvailabilityConfidence.VERIFIED,
            source="test_source",
        )
    )
    await repo.add_consensus_vintage(
        EconomicEventConsensusVintage(
            occurrence_key=key,
            revision_sequence=0,
            consensus_value=Decimal("3.1"),
            availability=_ts(2026, 8, 20),
            availability_confidence=AvailabilityConfidence.VERIFIED,
            source="test_source",
        )
    )
    await repo.add_actual_value_vintage(
        EconomicEventActualValueVintage(
            occurrence_key=key,
            revision_sequence=0,
            actual_value=Decimal("3.4"),
            availability=_ts(2026, 9, 4, 13, 30),
            availability_confidence=AvailabilityConfidence.VERIFIED,
            source="test_source",
        )
    )
    await repo.add_release_vintage(
        EconomicEventReleaseVintage(
            occurrence_key=key,
            revision_sequence=0,
            released_date=date(2026, 9, 4),
            released_time=None,
            released_timezone="UTC",
            availability=_ts(2026, 9, 4, 13, 30),
            availability_confidence=AvailabilityConfidence.VERIFIED,
            source="test_source",
        )
    )

    before_release = await use_case(key, _ts(2026, 9, 1))
    assert before_release is not None
    assert before_release.occurrence.occurrence_key == key
    assert before_release.schedule is not None
    assert before_release.consensus is not None
    assert before_release.actual is None
    assert before_release.first_release is None
    assert before_release.release is None

    after_release = await use_case(key, _ts(2026, 9, 4, 14, 0))
    assert after_release is not None
    assert after_release.actual is not None
    assert after_release.actual.actual_value == Decimal("3.4")
    assert after_release.first_release is not None
    assert after_release.first_release.actual_value == Decimal("3.4")
    assert after_release.release is not None
    assert after_release.release.released_date == date(2026, 9, 4)


@pytest.mark.asyncio
async def test_qualitative_occurrence_has_release_but_no_actual_value(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    use_case = GetEconomicEventState(repo)
    key = f"{TEST_OCCURRENCE_PREFIX}_FOMC"

    await repo.add_occurrence(
        EconomicEventOccurrence(
            occurrence_key=key, indicator_key="FOMC_PRESS_CONFERENCE", reference_period=None
        )
    )
    await repo.add_release_vintage(
        EconomicEventReleaseVintage(
            occurrence_key=key,
            revision_sequence=0,
            released_date=date(2026, 9, 17),
            released_time=None,
            released_timezone="UTC",
            availability=_ts(2026, 9, 17, 18, 5),
            availability_confidence=AvailabilityConfidence.VERIFIED,
            source="test_source",
        )
    )

    result = await use_case(key, _ts(2026, 9, 18))
    assert result is not None
    assert result.occurrence.reference_period is None
    assert result.release is not None
    assert result.actual is None
    assert result.first_release is None


@pytest.mark.asyncio
async def test_existing_occurrence_with_nothing_yet_knowable_returns_all_none_fields(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    use_case = GetEconomicEventState(repo)
    key = f"{TEST_OCCURRENCE_PREFIX}_EMPTY"
    await repo.add_occurrence(
        EconomicEventOccurrence(
            occurrence_key=key, indicator_key="US_NFP", reference_period=_ts(2026, 9, 4)
        )
    )

    result = await use_case(key, _ts(2020, 1, 1))

    assert result is not None
    assert result.schedule is None
    assert result.consensus is None
    assert result.actual is None
    assert result.first_release is None
    assert result.release is None
