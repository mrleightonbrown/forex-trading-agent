"""FX-41: point-in-time query semantics, exercised against the fake
repository. `FakeMacroObservationRepository` re-implements the same
filter/order rules as `SqlAlchemyMacroObservationRepository` -- see
tests/integration/test_macro_observation_repository.py for the live-
Postgres equivalents of the scenarios below.

Core invariant under test throughout: a query at timestamp T must never
return a vintage whose released_at is after T.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.application.ports.macro_observation_repository import (
    MacroObservationRepository,
)
from forex_agent.domain.macro_observation_vintage import MacroObservationVintage
from forex_agent.domain.timestamps import UtcTimestamp
from tests.fakes.macro_observation_repository import FakeMacroObservationRepository

SERIES_KEY = "US_CPI_YOY"


def _ts(*args: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(*args, tzinfo=UTC))


def test_fake_satisfies_macro_observation_repository_protocol() -> None:
    # Assignment alone is the check: mypy verifies
    # FakeMacroObservationRepository matches the MacroObservationRepository
    # Protocol shape structurally.
    fake: MacroObservationRepository = FakeMacroObservationRepository()
    assert fake is not None


@pytest.mark.asyncio
async def test_release_timing_february_observation_released_march_12() -> None:
    # FX-41 worked example: a February observation released March 12
    # 13:30 UTC must not be visible in a query the day before, and must
    # become visible from the exact release instant onward.
    fake = FakeMacroObservationRepository()
    february = _ts(2024, 2, 1)
    released_at = _ts(2024, 3, 12, 13, 30)
    await fake.add_vintage(
        MacroObservationVintage(
            series_key=SERIES_KEY,
            observation_period=february,
            value=Decimal("3.2"),
            released_at=released_at,
            revision_sequence=0,
            source="FRED",
        )
    )

    before_release = await fake.observation_as_known_at(SERIES_KEY, february, _ts(2024, 3, 11))
    assert before_release is None

    at_release = await fake.observation_as_known_at(SERIES_KEY, february, released_at)
    assert at_release is not None
    assert at_release.value == Decimal("3.2")

    after_release = await fake.observation_as_known_at(
        SERIES_KEY, february, _ts(2024, 3, 12, 13, 31)
    )
    assert after_release is not None
    assert after_release.value == Decimal("3.2")


@pytest.mark.asyncio
async def test_revision_initial_value_then_later_revision() -> None:
    # FX-41 worked example: initial value 2.1 available July 1; revision
    # 2.4 available August 1. A query at July 15 returns 2.1; a query at
    # August 15 returns 2.4 -- the earlier vintage is never overwritten,
    # it simply stops being the most recent one as of a later as-of time.
    fake = FakeMacroObservationRepository()
    period = _ts(2024, 6, 1)
    await fake.add_vintage(
        MacroObservationVintage(
            series_key=SERIES_KEY,
            observation_period=period,
            value=Decimal("2.1"),
            released_at=_ts(2024, 7, 1),
            revision_sequence=0,
            source="FRED",
        )
    )
    await fake.add_vintage(
        MacroObservationVintage(
            series_key=SERIES_KEY,
            observation_period=period,
            value=Decimal("2.4"),
            released_at=_ts(2024, 8, 1),
            revision_sequence=1,
            source="FRED",
        )
    )

    as_of_july_15 = await fake.observation_as_known_at(SERIES_KEY, period, _ts(2024, 7, 15))
    assert as_of_july_15 is not None
    assert as_of_july_15.value == Decimal("2.1")

    as_of_august_15 = await fake.observation_as_known_at(SERIES_KEY, period, _ts(2024, 8, 15))
    assert as_of_august_15 is not None
    assert as_of_august_15.value == Decimal("2.4")


@pytest.mark.asyncio
async def test_no_future_leakage_earlier_query_cannot_see_later_vintage() -> None:
    # Explicit no-future-leakage test: a vintage released in the future
    # relative to the as-of time must never be returned, by either query
    # method.
    fake = FakeMacroObservationRepository()
    period = _ts(2024, 6, 1)
    future_vintage = MacroObservationVintage(
        series_key=SERIES_KEY,
        observation_period=period,
        value=Decimal("99.9"),
        released_at=_ts(2099, 1, 1),
        revision_sequence=0,
        source="FRED",
    )
    await fake.add_vintage(future_vintage)

    assert await fake.observation_as_known_at(SERIES_KEY, period, _ts(2024, 1, 1)) is None
    assert await fake.latest_available_as_of(SERIES_KEY, _ts(2024, 1, 1)) is None


@pytest.mark.asyncio
async def test_latest_available_as_of_ignores_unreleased_future_period() -> None:
    fake = FakeMacroObservationRepository()
    await fake.add_vintage(
        MacroObservationVintage(
            series_key=SERIES_KEY,
            observation_period=_ts(2024, 1, 1),
            value=Decimal("3.0"),
            released_at=_ts(2024, 2, 12),
            revision_sequence=0,
            source="FRED",
        )
    )
    await fake.add_vintage(
        MacroObservationVintage(
            series_key=SERIES_KEY,
            observation_period=_ts(2024, 2, 1),
            value=Decimal("3.4"),
            released_at=_ts(2024, 3, 12),
            revision_sequence=0,
            source="FRED",
        )
    )

    # Both periods released by this point -- the February one is newer.
    result = await fake.latest_available_as_of(SERIES_KEY, _ts(2024, 4, 1))
    assert result is not None
    assert result.observation_period == _ts(2024, 2, 1)
    assert result.value == Decimal("3.4")

    # Only January has been released by this point.
    result = await fake.latest_available_as_of(SERIES_KEY, _ts(2024, 2, 20))
    assert result is not None
    assert result.observation_period == _ts(2024, 1, 1)
    assert result.value == Decimal("3.0")


@pytest.mark.asyncio
async def test_latest_available_as_of_reflects_most_recent_known_revision() -> None:
    fake = FakeMacroObservationRepository()
    period = _ts(2024, 6, 1)
    await fake.add_vintage(
        MacroObservationVintage(
            series_key=SERIES_KEY,
            observation_period=period,
            value=Decimal("2.1"),
            released_at=_ts(2024, 7, 1),
            revision_sequence=0,
            source="FRED",
        )
    )
    await fake.add_vintage(
        MacroObservationVintage(
            series_key=SERIES_KEY,
            observation_period=period,
            value=Decimal("2.4"),
            released_at=_ts(2024, 8, 1),
            revision_sequence=1,
            source="FRED",
        )
    )

    result = await fake.latest_available_as_of(SERIES_KEY, _ts(2024, 7, 15))
    assert result is not None
    assert result.value == Decimal("2.1")

    result = await fake.latest_available_as_of(SERIES_KEY, _ts(2024, 8, 15))
    assert result is not None
    assert result.value == Decimal("2.4")


@pytest.mark.asyncio
async def test_add_vintage_is_idempotent_for_identical_identity() -> None:
    fake = FakeMacroObservationRepository()
    period = _ts(2024, 6, 1)
    vintage = MacroObservationVintage(
        series_key=SERIES_KEY,
        observation_period=period,
        value=Decimal("2.1"),
        released_at=_ts(2024, 7, 1),
        revision_sequence=0,
        source="FRED",
    )
    await fake.add_vintage(vintage)
    await fake.add_vintage(vintage)

    assert len(fake._vintages) == 1  # whitebox check of the fake itself


@pytest.mark.asyncio
async def test_different_series_do_not_leak_into_each_other() -> None:
    fake = FakeMacroObservationRepository()
    period = _ts(2024, 6, 1)
    await fake.add_vintage(
        MacroObservationVintage(
            series_key="US_CPI_YOY",
            observation_period=period,
            value=Decimal("2.1"),
            released_at=_ts(2024, 7, 1),
            revision_sequence=0,
            source="FRED",
        )
    )

    result = await fake.observation_as_known_at("EA_CPI_YOY", period, _ts(2024, 8, 1))
    assert result is None
