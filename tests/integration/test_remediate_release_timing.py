"""FX-44H: `RemediateReleaseTiming` against live Postgres. See
tests/unit/application/test_remediate_release_timing.py for the fast,
DB-free equivalents of the core scenarios exercised here.

Requires a live Postgres with migrations applied — run
`docker compose up -d db && uv run alembic upgrade head` first.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.application.use_cases.remediate_release_timing import (
    RemediateReleaseTiming,
    RemediationOutcome,
)
from forex_agent.domain.macro_observation_vintage import MacroObservationVintage
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.macro_observation_repository import (
    SqlAlchemyMacroObservationRepository,
)
from forex_agent.infrastructure.db.models.macro_observation_vintage import (
    MacroObservationVintageRow,
)
from forex_agent.infrastructure.db.session import get_engine

TEST_SERIES_KEY = "__test_usd_remediation__"


def _ts(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
    microsecond: int = 0,
) -> UtcTimestamp:
    return UtcTimestamp(datetime(year, month, day, hour, minute, second, microsecond, tzinfo=UTC))


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
async def test_stale_exact_row_is_corrected_through_the_repository(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyMacroObservationRepository(session)
    stale = MacroObservationVintage(
        series_key=TEST_SERIES_KEY,
        observation_period=_ts(2018, 6, 14),
        value=Decimal("1.875"),
        released_at=_ts(2018, 6, 14),  # FX-44's original, wrong value
        revision_sequence=0,
        source="FRED",
        released_at_is_verified=True,
    )
    await repo.add_vintage(stale)
    remediate = RemediateReleaseTiming(repository=repo)

    [record] = await remediate("USD", TEST_SERIES_KEY)

    assert record.outcome is RemediationOutcome.CORRECTED
    expected_released_at = UtcTimestamp(datetime(2018, 6, 13, 18, 0, 0, tzinfo=UTC))
    assert record.corrected_released_at == expected_released_at

    stored = await repo.observation_as_known_at(TEST_SERIES_KEY, _ts(2018, 6, 14), _ts(2099, 1, 1))
    assert stored is not None
    assert stored.released_at == expected_released_at
    assert stored.effective_at == _ts(2018, 6, 14)
    assert stored.released_at_is_verified is True


@pytest.mark.asyncio
async def test_rerun_is_idempotent(session: AsyncSession) -> None:
    # FX-44H test requirement: corrected classified rows can be
    # remediated once and are idempotent.
    repo = SqlAlchemyMacroObservationRepository(session)
    await repo.add_vintage(
        MacroObservationVintage(
            series_key=TEST_SERIES_KEY,
            observation_period=_ts(2018, 6, 14),
            value=Decimal("1.875"),
            released_at=_ts(2018, 6, 14),
            revision_sequence=0,
            source="FRED",
            released_at_is_verified=True,
        )
    )
    remediate = RemediateReleaseTiming(repository=repo)

    first = await remediate("USD", TEST_SERIES_KEY)
    assert first[0].outcome is RemediationOutcome.CORRECTED

    second = await remediate("USD", TEST_SERIES_KEY)
    assert second[0].outcome is RemediationOutcome.ALREADY_CORRECT

    stored = await repo.observation_as_known_at(TEST_SERIES_KEY, _ts(2018, 6, 14), _ts(2099, 1, 1))
    assert stored is not None
    assert stored.released_at == UtcTimestamp(datetime(2018, 6, 13, 18, 0, 0, tzinfo=UTC))


@pytest.mark.asyncio
async def test_2015_and_2016_rows_remediated_with_corrected_effective_dates(
    session: AsyncSession,
) -> None:
    # FX-44H.1: reproduces FX-44H's own historical bug exactly -- both
    # rows seeded with released_at ALREADY correct (FX-44H got the
    # decision timestamp right for these two) but effective_at wrongly
    # equal to the stored date instead of one day later. Verifies both
    # corrections directly, and that value/revision_sequence/series_key
    # /observation identity are all preserved.
    repo = SqlAlchemyMacroObservationRepository(session)
    await repo.add_vintage(
        MacroObservationVintage(
            series_key=TEST_SERIES_KEY,
            observation_period=_ts(2015, 12, 16),
            value=Decimal("0.375"),
            released_at=UtcTimestamp(datetime(2015, 12, 16, 19, 0, 0, tzinfo=UTC)),
            effective_at=_ts(2015, 12, 16),  # FX-44H's own bug
            revision_sequence=0,
            source="FRED",
            released_at_is_verified=True,
        )
    )
    await repo.add_vintage(
        MacroObservationVintage(
            series_key=TEST_SERIES_KEY,
            observation_period=_ts(2016, 12, 14),
            value=Decimal("0.625"),
            released_at=UtcTimestamp(datetime(2016, 12, 14, 19, 0, 0, tzinfo=UTC)),
            effective_at=_ts(2016, 12, 14),  # FX-44H's own bug
            revision_sequence=0,
            source="FRED",
            released_at_is_verified=True,
        )
    )
    remediate = RemediateReleaseTiming(repository=repo)

    records = await remediate("USD", TEST_SERIES_KEY)
    by_period = {r.observation_period: r for r in records}
    assert by_period[_ts(2015, 12, 16)].outcome is RemediationOutcome.CORRECTED
    assert by_period[_ts(2016, 12, 14)].outcome is RemediationOutcome.CORRECTED

    result_2015 = await repo.observation_as_known_at(
        TEST_SERIES_KEY, _ts(2015, 12, 16), _ts(2099, 1, 1)
    )
    assert result_2015 is not None
    assert result_2015.released_at.value == datetime(2015, 12, 16, 19, 0, 0, tzinfo=UTC)
    assert result_2015.effective_at is not None
    assert result_2015.effective_at.value == datetime(2015, 12, 17, 0, 0, 0, tzinfo=UTC)
    assert result_2015.value == Decimal("0.375")  # unchanged
    assert result_2015.revision_sequence == 0  # unchanged
    assert result_2015.series_key == TEST_SERIES_KEY  # unchanged
    assert result_2015.observation_period == _ts(2015, 12, 16)  # unchanged

    result_2016 = await repo.observation_as_known_at(
        TEST_SERIES_KEY, _ts(2016, 12, 14), _ts(2099, 1, 1)
    )
    assert result_2016 is not None
    assert result_2016.released_at.value == datetime(2016, 12, 14, 19, 0, 0, tzinfo=UTC)
    assert result_2016.effective_at is not None
    assert result_2016.effective_at.value == datetime(2016, 12, 15, 0, 0, 0, tzinfo=UTC)
    assert result_2016.value == Decimal("0.625")
    assert result_2016.revision_sequence == 0
    assert result_2016.series_key == TEST_SERIES_KEY
    assert result_2016.observation_period == _ts(2016, 12, 14)

    # Idempotent rerun -- zero new corrections, both ALREADY_CORRECT.
    second = await remediate("USD", TEST_SERIES_KEY)
    second_by_period = {r.observation_period: r for r in second}
    assert second_by_period[_ts(2015, 12, 16)].outcome is RemediationOutcome.ALREADY_CORRECT
    assert second_by_period[_ts(2016, 12, 14)].outcome is RemediationOutcome.ALREADY_CORRECT


@pytest.mark.asyncio
async def test_corrected_release_timestamp_remains_invisible_before_its_time(
    session: AsyncSession,
) -> None:
    # FX-44H.1 test requirement: release timestamp remains invisible
    # before the FOMC statement time -- re-confirmed for one of the two
    # newly-corrected rows specifically, not just the FX-44H example.
    repo = SqlAlchemyMacroObservationRepository(session)
    await repo.add_vintage(
        MacroObservationVintage(
            series_key=TEST_SERIES_KEY,
            observation_period=_ts(2015, 12, 16),
            value=Decimal("0.375"),
            released_at=UtcTimestamp(datetime(2015, 12, 16, 19, 0, 0, tzinfo=UTC)),
            effective_at=_ts(2015, 12, 16),
            revision_sequence=0,
            source="FRED",
            released_at_is_verified=True,
        )
    )
    remediate = RemediateReleaseTiming(repository=repo)
    await remediate("USD", TEST_SERIES_KEY)  # corrects effective_at only; released_at unchanged

    just_before = await repo.observation_as_known_at(
        TEST_SERIES_KEY,
        _ts(2015, 12, 16),
        UtcTimestamp(datetime(2015, 12, 16, 18, 59, 59, tzinfo=UTC)),
    )
    at_release = await repo.observation_as_known_at(
        TEST_SERIES_KEY,
        _ts(2015, 12, 16),
        UtcTimestamp(datetime(2015, 12, 16, 19, 0, 0, tzinfo=UTC)),
    )

    assert just_before is None
    assert at_release is not None
