"""FX-41: `SqlAlchemyMacroObservationRepository` round-trip and point-in-time
query tests against live Postgres. FX-41H: conflict/idempotency hardening
and deterministic tie-breaking tests.

Requires a live Postgres with the FX-41 migration applied — run
`docker compose up -d db && uv run alembic upgrade head` first. See
tests/unit/application/test_fake_macro_observation_repository.py for the
fast, DB-free equivalents of the core scenarios exercised here.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.application.ports.macro_observation_repository import (
    MacroVintageConflictError,
    VintageWriteOutcome,
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
    # FX-41H: revisions must not destructively overwrite. Attempting to
    # add a vintage with the same (series_key, observation_period,
    # revision_sequence) but a different value must raise
    # MacroVintageConflictError -- the originally stored value must survive.
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
    with pytest.raises(MacroVintageConflictError):
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


def _base_vintage(period: UtcTimestamp) -> MacroObservationVintage:
    return MacroObservationVintage(
        series_key=TEST_SERIES_KEY,
        observation_period=period,
        value=Decimal("2.1"),
        released_at=_ts(2024, 7, 1),
        revision_sequence=0,
        source="FRED",
    )


@pytest.mark.asyncio
async def test_exact_duplicate_add_vintage_succeeds_without_duplicating(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyMacroObservationRepository(session)
    period = _ts(2024, 6, 1)
    vintage = _base_vintage(period)

    first = await repo.add_vintage(vintage)
    second = await repo.add_vintage(vintage)  # must not raise

    assert first is VintageWriteOutcome.INSERTED
    assert second is VintageWriteOutcome.ALREADY_PRESENT

    stored = (
        (
            await session.execute(
                select(MacroObservationVintageRow).where(
                    MacroObservationVintageRow.series_key == TEST_SERIES_KEY,
                    MacroObservationVintageRow.observation_period == period.value,
                    MacroObservationVintageRow.revision_sequence == 0,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(stored) == 1


@pytest.mark.asyncio
async def test_same_identity_different_value_is_a_conflict(session: AsyncSession) -> None:
    repo = SqlAlchemyMacroObservationRepository(session)
    period = _ts(2024, 6, 1)
    original = _base_vintage(period)
    different_value = MacroObservationVintage(
        series_key=TEST_SERIES_KEY,
        observation_period=period,
        value=Decimal("9.9"),
        released_at=original.released_at,
        revision_sequence=0,
        source="FRED",
    )
    await repo.add_vintage(original)

    with pytest.raises(MacroVintageConflictError):
        await repo.add_vintage(different_value)

    result = await repo.observation_as_known_at(TEST_SERIES_KEY, period, _ts(2024, 7, 15))
    assert result is not None
    assert result.value == Decimal("2.1")


@pytest.mark.asyncio
async def test_same_identity_different_released_at_is_a_conflict(session: AsyncSession) -> None:
    repo = SqlAlchemyMacroObservationRepository(session)
    period = _ts(2024, 6, 1)
    original = _base_vintage(period)
    different_released_at = MacroObservationVintage(
        series_key=TEST_SERIES_KEY,
        observation_period=period,
        value=original.value,
        released_at=_ts(2024, 7, 2),
        revision_sequence=0,
        source="FRED",
    )
    await repo.add_vintage(original)

    with pytest.raises(MacroVintageConflictError):
        await repo.add_vintage(different_released_at)

    result = await repo.observation_as_known_at(TEST_SERIES_KEY, period, _ts(2024, 7, 15))
    assert result is not None
    assert result.released_at == original.released_at


@pytest.mark.asyncio
async def test_same_identity_different_source_is_a_conflict(session: AsyncSession) -> None:
    repo = SqlAlchemyMacroObservationRepository(session)
    period = _ts(2024, 6, 1)
    original = _base_vintage(period)
    different_source = MacroObservationVintage(
        series_key=TEST_SERIES_KEY,
        observation_period=period,
        value=original.value,
        released_at=original.released_at,
        revision_sequence=0,
        source="ECB_SDW",
    )
    await repo.add_vintage(original)

    with pytest.raises(MacroVintageConflictError):
        await repo.add_vintage(different_source)

    result = await repo.observation_as_known_at(TEST_SERIES_KEY, period, _ts(2024, 7, 15))
    assert result is not None
    assert result.source == "FRED"


@pytest.mark.asyncio
async def test_same_identity_different_effective_at_is_a_conflict(session: AsyncSession) -> None:
    repo = SqlAlchemyMacroObservationRepository(session)
    period = _ts(2024, 6, 1)
    original = _base_vintage(period)
    different_effective_at = MacroObservationVintage(
        series_key=TEST_SERIES_KEY,
        observation_period=period,
        value=original.value,
        released_at=original.released_at,
        revision_sequence=0,
        source="FRED",
        effective_at=_ts(2024, 8, 1),
    )
    await repo.add_vintage(original)

    with pytest.raises(MacroVintageConflictError):
        await repo.add_vintage(different_effective_at)

    result = await repo.observation_as_known_at(TEST_SERIES_KEY, period, _ts(2024, 7, 15))
    assert result is not None
    assert result.effective_at is None


@pytest.mark.asyncio
async def test_conflict_error_carries_existing_and_incoming_vintages(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyMacroObservationRepository(session)
    period = _ts(2024, 6, 1)
    original = _base_vintage(period)
    conflicting = MacroObservationVintage(
        series_key=TEST_SERIES_KEY,
        observation_period=period,
        value=Decimal("9.9"),
        released_at=original.released_at,
        revision_sequence=0,
        source="FRED",
    )
    await repo.add_vintage(original)

    with pytest.raises(MacroVintageConflictError) as excinfo:
        await repo.add_vintage(conflicting)

    assert excinfo.value.existing.value == Decimal("2.1")
    assert excinfo.value.incoming.value == Decimal("9.9")


@pytest.mark.asyncio
async def test_tie_break_by_revision_sequence_when_released_at_matches(
    session: AsyncSession,
) -> None:
    # FX-41H: two vintages of the same observation_period sharing the same
    # released_at must resolve deterministically to the higher
    # revision_sequence, not to whichever row the database happens to scan
    # first.
    repo = SqlAlchemyMacroObservationRepository(session)
    period = _ts(2024, 6, 1)
    shared_released_at = _ts(2024, 7, 1)
    lower_revision = MacroObservationVintage(
        series_key=TEST_SERIES_KEY,
        observation_period=period,
        value=Decimal("2.1"),
        released_at=shared_released_at,
        revision_sequence=0,
        source="FRED",
    )
    higher_revision = MacroObservationVintage(
        series_key=TEST_SERIES_KEY,
        observation_period=period,
        value=Decimal("2.4"),
        released_at=shared_released_at,
        revision_sequence=1,
        source="FRED",
    )
    # Inserted in ascending order so a naive "first match wins" scan would
    # return the wrong (lower-revision) vintage.
    await repo.add_vintage(lower_revision)
    await repo.add_vintage(higher_revision)

    known_at = await repo.observation_as_known_at(TEST_SERIES_KEY, period, _ts(2024, 7, 15))
    assert known_at is not None
    assert known_at.value == Decimal("2.4")
    assert known_at.revision_sequence == 1

    latest = await repo.latest_available_as_of(TEST_SERIES_KEY, _ts(2024, 7, 15))
    assert latest is not None
    assert latest.value == Decimal("2.4")
    assert latest.revision_sequence == 1


# ---------------------------------------------------------------------------
# FX-43H: replace_provisional_release_timing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replace_provisional_release_timing_corrects_in_place(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyMacroObservationRepository(session)
    period = _ts(2024, 6, 1)
    proxy_released_at = period
    provisional = MacroObservationVintage(
        series_key=TEST_SERIES_KEY,
        observation_period=period,
        value=Decimal("2.1"),
        released_at=proxy_released_at,
        revision_sequence=0,
        source="FRED",
        released_at_is_verified=False,
    )
    await repo.add_vintage(provisional)

    verified_released_at = _ts(2024, 5, 30)
    verified_effective_at = period
    await repo.replace_provisional_release_timing(
        TEST_SERIES_KEY, period, 0, verified_released_at, verified_effective_at
    )

    corrected = await repo.observation_as_known_at(TEST_SERIES_KEY, period, verified_released_at)
    assert corrected is not None
    assert corrected.released_at == verified_released_at
    assert corrected.effective_at == verified_effective_at
    assert corrected.released_at_is_verified is True
    assert corrected.value == Decimal("2.1")
    assert corrected.revision_sequence == 0

    # Exactly one row for this identity -- the old proxy timestamp is gone,
    # not left as a second, still-visible row.
    stored = (
        (
            await session.execute(
                select(MacroObservationVintageRow).where(
                    MacroObservationVintageRow.series_key == TEST_SERIES_KEY,
                    MacroObservationVintageRow.observation_period == period.value,
                    MacroObservationVintageRow.revision_sequence == 0,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(stored) == 1
    assert stored[0].released_at == verified_released_at.value


@pytest.mark.asyncio
async def test_replace_provisional_release_timing_rejects_missing_identity(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyMacroObservationRepository(session)

    with pytest.raises(ValueError, match="no vintage exists"):
        await repo.replace_provisional_release_timing(
            TEST_SERIES_KEY, _ts(2024, 6, 1), 0, _ts(2024, 6, 1), None
        )


@pytest.mark.asyncio
async def test_replace_provisional_release_timing_rejects_already_verified_row(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyMacroObservationRepository(session)
    period = _ts(2024, 6, 1)
    already_verified = MacroObservationVintage(
        series_key=TEST_SERIES_KEY,
        observation_period=period,
        value=Decimal("2.1"),
        released_at=_ts(2024, 7, 1),
        revision_sequence=0,
        source="FRED",
        released_at_is_verified=True,
    )
    await repo.add_vintage(already_verified)

    with pytest.raises(ValueError, match="already released_at_is_verified=True"):
        await repo.replace_provisional_release_timing(
            TEST_SERIES_KEY, period, 0, _ts(2024, 6, 15), None
        )

    result = await repo.observation_as_known_at(TEST_SERIES_KEY, period, _ts(2024, 7, 1))
    assert result is not None
    assert result.released_at == _ts(2024, 7, 1)


@pytest.mark.asyncio
async def test_concurrent_replace_provisional_release_timing_only_one_wins(
    session: AsyncSession,
) -> None:
    """FX-43H.1 regression: this is the test the SELECT-then-UPDATE
    version of `replace_provisional_release_timing` could NOT pass
    reliably -- two genuinely concurrent verification attempts, each on
    its own session/connection, racing the identical provisional
    identity via `asyncio.gather`. Exactly one must succeed and the
    other must observe the already-verified failure; the atomic
    conditional UPDATE's `WHERE released_at_is_verified = false`
    predicate, re-evaluated against the post-commit row by whichever
    attempt is serialized second, is what this depends on.
    """
    setup_repo = SqlAlchemyMacroObservationRepository(session)
    period = _ts(2024, 6, 1)
    provisional = MacroObservationVintage(
        series_key=TEST_SERIES_KEY,
        observation_period=period,
        value=Decimal("2.1"),
        released_at=period,
        revision_sequence=0,
        source="FRED",
        released_at_is_verified=False,
    )
    await setup_repo.add_vintage(provisional)

    # Two independent sessions -- each its own connection -- so the two
    # attempts below are genuinely separate database transactions, not
    # two operations sharing one session's single connection.
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)

    async def _attempt(candidate_released_at: UtcTimestamp) -> str | None:
        async with session_factory() as race_session:
            race_repo = SqlAlchemyMacroObservationRepository(race_session)
            try:
                await race_repo.replace_provisional_release_timing(
                    TEST_SERIES_KEY, period, 0, candidate_released_at, None
                )
            except ValueError as exc:
                return str(exc)
            return None

    outcomes = await asyncio.gather(
        _attempt(_ts(2024, 5, 30)),
        _attempt(_ts(2024, 5, 31)),
    )

    successes = [outcome for outcome in outcomes if outcome is None]
    failures = [outcome for outcome in outcomes if outcome is not None]
    assert len(successes) == 1, f"expected exactly one winner, got outcomes={outcomes!r}"
    assert len(failures) == 1
    assert "already released_at_is_verified=True" in failures[0]

    final = await setup_repo.observation_as_known_at(TEST_SERIES_KEY, period, _ts(2024, 12, 31))
    assert final is not None
    assert final.released_at_is_verified is True
    assert final.released_at in (_ts(2024, 5, 30), _ts(2024, 5, 31))
