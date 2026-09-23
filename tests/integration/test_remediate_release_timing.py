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
