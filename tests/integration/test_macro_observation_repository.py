"""FX-41: `SqlAlchemyMacroObservationRepository` round-trip and point-in-time
query tests against live Postgres.

Requires a live Postgres with the FX-41 migration applied — run
`docker compose up -d db && uv run alembic upgrade head` first. See
tests/unit/application/test_fake_macro_observation_repository.py for the
fast, DB-free equivalents of the core scenarios exercised here.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.domain.macro_observation_vintage import MacroObservationVintage
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.macro_observation_repository import (
    SqlAlchemyMacroObservationRepository,
)
from forex_agent.infrastructure.db.models.macro_observation_vintage import (
    MacroObservationVintageRow,
)
from forex_agent.infrastructure.db.session import get_engine

# A series key unlikely to ever be real, to keep test rows unambiguous.
TEST_SERIES_KEY = "__test_macro_series__"


def _ts(*args: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(*args, tzinfo=UTC))


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    async with session_factory() as db_session:
        yield db_session

    async with session_factory() as cleanup_session:
        await cleanup_session.execute(
            delete(MacroObservationVintageRow).where(
                MacroObservationVintageRow.series_key == TEST_SERIES_KEY
            )
        )
        await cleanup_session.commit()


@pytest.mark.asyncio
async def test_observation_as_known_at_returns_none_when_nothing_stored(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyMacroObservationRepository(session)

    result = await repo.observation_as_known_at(TEST_SERIES_KEY, _ts(2024, 2, 1), _ts(2024, 4, 1))

    assert result is None


@pytest.mark.asyncio
async def test_release_timing_february_observation_released_march_12(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyMacroObservationRepository(session)
    february = _ts(2024, 2, 1)
    released_at = _ts(2024, 3, 12, 13, 30)
    await repo.add_vintage(
        MacroObservationVintage(
            series_key=TEST_SERIES_KEY,
            observation_period=february,
            value=Decimal("3.2"),
            released_at=released_at,
            revision_sequence=0,
            source="FRED",
        )
    )

    before_release = await repo.observation_as_known_at(TEST_SERIES_KEY, february, _ts(2024, 3, 11))
    assert before_release is None

    after_release = await repo.observation_as_known_at(
        TEST_SERIES_KEY, february, _ts(2024, 3, 12, 13, 31)
    )
    assert after_release is not None
    assert after_release.value == Decimal("3.2")


@pytest.mark.asyncio
async def test_revision_initial_value_then_later_revision(session: AsyncSession) -> None:
    repo = SqlAlchemyMacroObservationRepository(session)
    period = _ts(2024, 6, 1)
    await repo.add_vintage(
        MacroObservationVintage(
            series_key=TEST_SERIES_KEY,
            observation_period=period,
            value=Decimal("2.1"),
            released_at=_ts(2024, 7, 1),
            revision_sequence=0,
            source="FRED",
        )
    )
    await repo.add_vintage(
        MacroObservationVintage(
            series_key=TEST_SERIES_KEY,
            observation_period=period,
            value=Decimal("2.4"),
            released_at=_ts(2024, 8, 1),
            revision_sequence=1,
            source="FRED",
        )
    )

    as_of_july_15 = await repo.observation_as_known_at(TEST_SERIES_KEY, period, _ts(2024, 7, 15))
    assert as_of_july_15 is not None
    assert as_of_july_15.value == Decimal("2.1")

    as_of_august_15 = await repo.observation_as_known_at(TEST_SERIES_KEY, period, _ts(2024, 8, 15))
    assert as_of_august_15 is not None
    assert as_of_august_15.value == Decimal("2.4")


@pytest.mark.asyncio
async def test_no_future_leakage_earlier_query_cannot_see_later_vintage(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyMacroObservationRepository(session)
    period = _ts(2024, 6, 1)
    await repo.add_vintage(
        MacroObservationVintage(
            series_key=TEST_SERIES_KEY,
            observation_period=period,
            value=Decimal("99.9"),
            released_at=_ts(2099, 1, 1),
            revision_sequence=0,
            source="FRED",
        )
    )

    assert await repo.observation_as_known_at(TEST_SERIES_KEY, period, _ts(2024, 1, 1)) is None
    assert await repo.latest_available_as_of(TEST_SERIES_KEY, _ts(2024, 1, 1)) is None


@pytest.mark.asyncio
async def test_latest_available_as_of_reflects_most_recent_known_period_and_revision(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyMacroObservationRepository(session)
    await repo.add_vintage(
        MacroObservationVintage(
            series_key=TEST_SERIES_KEY,
            observation_period=_ts(2024, 1, 1),
            value=Decimal("3.0"),
            released_at=_ts(2024, 2, 12),
            revision_sequence=0,
            source="FRED",
        )
    )
    await repo.add_vintage(
        MacroObservationVintage(
            series_key=TEST_SERIES_KEY,
            observation_period=_ts(2024, 2, 1),
            value=Decimal("3.4"),
            released_at=_ts(2024, 3, 12),
            revision_sequence=0,
            source="FRED",
        )
    )

    only_january_known = await repo.latest_available_as_of(TEST_SERIES_KEY, _ts(2024, 2, 20))
    assert only_january_known is not None
    assert only_january_known.value == Decimal("3.0")

    both_known = await repo.latest_available_as_of(TEST_SERIES_KEY, _ts(2024, 4, 1))
    assert both_known is not None
    assert both_known.value == Decimal("3.4")


@pytest.mark.asyncio
async def test_add_vintage_never_overwrites_an_existing_vintage(session: AsyncSession) -> None:
    # FX-41: revisions must not destructively overwrite. Attempting to
    # add a vintage with the same (series_key, observation_period,
    # revision_sequence) but a different value must be a no-op -- the
    # originally stored value must survive.
    repo = SqlAlchemyMacroObservationRepository(session)
    period = _ts(2024, 6, 1)
    original = MacroObservationVintage(
        series_key=TEST_SERIES_KEY,
        observation_period=period,
        value=Decimal("2.1"),
        released_at=_ts(2024, 7, 1),
        revision_sequence=0,
        source="FRED",
    )
    conflicting = MacroObservationVintage(
        series_key=TEST_SERIES_KEY,
        observation_period=period,
        value=Decimal("999.9"),
        released_at=_ts(2024, 7, 1),
        revision_sequence=0,
        source="FRED",
    )
    await repo.add_vintage(original)
    await repo.add_vintage(conflicting)

    result = await repo.observation_as_known_at(TEST_SERIES_KEY, period, _ts(2024, 7, 15))
    assert result is not None
    assert result.value == Decimal("2.1")


@pytest.mark.asyncio
async def test_decimal_fidelity_round_trips_through_postgres(session: AsyncSession) -> None:
    repo = SqlAlchemyMacroObservationRepository(session)
    period = _ts(2024, 6, 1)
    precise = Decimal("2.123456789")
    await repo.add_vintage(
        MacroObservationVintage(
            series_key=TEST_SERIES_KEY,
            observation_period=period,
            value=precise,
            released_at=_ts(2024, 7, 1),
            revision_sequence=0,
            source="FRED",
        )
    )

    result = await repo.observation_as_known_at(TEST_SERIES_KEY, period, _ts(2024, 7, 15))

    assert result is not None
    assert result.value == precise
    assert isinstance(result.value, Decimal)
