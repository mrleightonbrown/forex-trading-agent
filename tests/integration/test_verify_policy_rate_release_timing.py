"""FX-44: `VerifyPolicyRateReleaseTiming` and `require_research_ready_
interval` against live Postgres. See tests/unit/application/
test_verify_policy_rate_release_timing.py for the fast, DB-free
equivalents of the core scenarios exercised here.

Requires a live Postgres with migrations applied — run
`docker compose up -d db && uv run alembic upgrade head` first.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.application.use_cases.verify_policy_rate_release_timing import (
    ChangePointOutcome,
    VerifyPolicyRateReleaseTiming,
)
from forex_agent.domain.macro_observation_vintage import MacroObservationVintage
from forex_agent.domain.research_readiness import (
    ResearchIntervalNotReadyError,
    require_research_ready_interval,
)
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.macro_observation_repository import (
    SqlAlchemyMacroObservationRepository,
)
from forex_agent.infrastructure.db.models.macro_observation_vintage import (
    MacroObservationVintageRow,
)
from forex_agent.infrastructure.db.session import get_engine

# A series key unlikely to ever be real, to keep test rows unambiguous --
# matches USD's currency so the registry's USD rules genuinely apply.
TEST_SERIES_KEY = "__test_usd_policy_rate__"


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


def _provisional_vintage(period_args: tuple[int, ...]) -> MacroObservationVintage:
    return MacroObservationVintage(
        series_key=TEST_SERIES_KEY,
        observation_period=_ts(*period_args),
        value=Decimal("2.0"),
        released_at=_ts(*period_args),
        revision_sequence=0,
        source="FRED",
    )


@pytest.mark.asyncio
async def test_verified_observation_is_replaced_through_the_repository(
    session: AsyncSession,
) -> None:
    # FX-44 test requirement: verified observation is replaced through
    # the repository.
    repo = SqlAlchemyMacroObservationRepository(session)
    await repo.add_vintage(_provisional_vintage((2018, 6, 14)))
    use_case = VerifyPolicyRateReleaseTiming(repository=repo)

    report = await use_case("USD", TEST_SERIES_KEY)

    [cp] = report.change_points
    assert cp.outcome is ChangePointOutcome.EXACT
    assert cp.newly_applied is True

    stored = await repo.observation_as_known_at(TEST_SERIES_KEY, _ts(2018, 6, 14), _ts(2099, 1, 1))
    assert stored is not None
    assert stored.released_at_is_verified is True
    assert stored.released_at.value == datetime(2018, 6, 14, 18, 0, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_rerun_does_not_rewrite_an_already_verified_timestamp(
    session: AsyncSession,
) -> None:
    # FX-44 test requirement: rerun does not rewrite an already-verified
    # timestamp.
    repo = SqlAlchemyMacroObservationRepository(session)
    await repo.add_vintage(_provisional_vintage((2018, 6, 14)))
    use_case = VerifyPolicyRateReleaseTiming(repository=repo)

    await use_case("USD", TEST_SERIES_KEY)
    second_report = await use_case("USD", TEST_SERIES_KEY)

    [cp] = second_report.change_points
    assert cp.outcome is ChangePointOutcome.EXACT
    assert cp.newly_applied is False

    stored = await repo.observation_as_known_at(TEST_SERIES_KEY, _ts(2018, 6, 14), _ts(2099, 1, 1))
    assert stored is not None
    assert stored.released_at.value == datetime(2018, 6, 14, 18, 0, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_unresolved_observation_remains_provisional(session: AsyncSession) -> None:
    repo = SqlAlchemyMacroObservationRepository(session)
    await repo.add_vintage(_provisional_vintage((2008, 1, 22)))  # known irregular date
    use_case = VerifyPolicyRateReleaseTiming(repository=repo)

    report = await use_case("USD", TEST_SERIES_KEY)

    [cp] = report.change_points
    assert cp.outcome is ChangePointOutcome.UNRESOLVED

    stored = await repo.observation_as_known_at(TEST_SERIES_KEY, _ts(2008, 1, 22), _ts(2099, 1, 1))
    assert stored is not None
    assert stored.released_at_is_verified is False
    assert stored.released_at_is_conservative_bound is False


@pytest.mark.asyncio
async def test_mixed_verified_and_provisional_range_fails_research_readiness(
    session: AsyncSession,
) -> None:
    # FX-44 test requirement: mixed verified/provisional range is
    # rejected as research-ready -- exercised here against vintages
    # actually round-tripped through real Postgres, not just in-memory
    # domain objects.
    repo = SqlAlchemyMacroObservationRepository(session)
    await repo.add_vintage(_provisional_vintage((2018, 6, 14)))  # will resolve EXACT
    await repo.add_vintage(_provisional_vintage((2008, 1, 22)))  # stays provisional
    use_case = VerifyPolicyRateReleaseTiming(repository=repo)
    await use_case("USD", TEST_SERIES_KEY)

    vintages = await repo.list_all_for_series(TEST_SERIES_KEY)

    with pytest.raises(ResearchIntervalNotReadyError):
        require_research_ready_interval(vintages, _ts(2000, 1, 1), _ts(2099, 1, 1))


@pytest.mark.asyncio
async def test_fully_resolved_range_passes_research_readiness(session: AsyncSession) -> None:
    repo = SqlAlchemyMacroObservationRepository(session)
    await repo.add_vintage(_provisional_vintage((2018, 6, 14)))  # resolves EXACT
    await repo.add_vintage(_provisional_vintage((1994, 2, 4)))  # resolves CONSERVATIVE_SAFE_BOUND
    use_case = VerifyPolicyRateReleaseTiming(repository=repo)
    await use_case("USD", TEST_SERIES_KEY)

    vintages = await repo.list_all_for_series(TEST_SERIES_KEY)

    require_research_ready_interval(vintages, _ts(1990, 1, 1), _ts(2099, 1, 1))  # must not raise


@pytest.mark.asyncio
async def test_future_timestamp_never_visible_before_its_release_time(
    session: AsyncSession,
) -> None:
    # FX-44 test requirement: a future timestamp can never become
    # visible before its release time.
    repo = SqlAlchemyMacroObservationRepository(session)
    await repo.add_vintage(_provisional_vintage((2018, 6, 14)))
    use_case = VerifyPolicyRateReleaseTiming(repository=repo)
    await use_case("USD", TEST_SERIES_KEY)  # corrects released_at to 2018-06-14T18:00:00Z

    just_before = await repo.observation_as_known_at(
        TEST_SERIES_KEY,
        _ts(2018, 6, 14),
        UtcTimestamp(datetime(2018, 6, 14, 17, 59, 59, tzinfo=UTC)),
    )
    at_release = await repo.observation_as_known_at(
        TEST_SERIES_KEY, _ts(2018, 6, 14), UtcTimestamp(datetime(2018, 6, 14, 18, 0, 0, tzinfo=UTC))
    )

    assert just_before is None
    assert at_release is not None
