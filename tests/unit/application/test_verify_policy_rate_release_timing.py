"""FX-44: fast, DB-free tests for `VerifyPolicyRateReleaseTiming`
against `FakeMacroObservationRepository`. See
tests/integration/test_verify_policy_rate_release_timing.py for the
live-Postgres equivalents of the core scenarios exercised here."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.application.use_cases.verify_policy_rate_release_timing import (
    ChangePointOutcome,
    VerifyPolicyRateReleaseTiming,
)
from forex_agent.domain.macro_observation_vintage import MacroObservationVintage
from forex_agent.domain.timestamps import UtcTimestamp
from tests.fakes.macro_observation_repository import FakeMacroObservationRepository

SERIES_KEY = "USD_POLICY_RATE"


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


def _provisional_vintage(
    period_args: tuple[int, ...], **overrides: object
) -> MacroObservationVintage:
    defaults: dict[str, object] = {
        "series_key": SERIES_KEY,
        "observation_period": _ts(*period_args),
        "value": Decimal("2.0"),
        "released_at": _ts(*period_args),
        "revision_sequence": 0,
        "source": "FRED",
    }
    defaults.update(overrides)
    return MacroObservationVintage(**defaults)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_regular_post_2013_date_is_newly_classified_exact() -> None:
    fake = FakeMacroObservationRepository()
    await fake.add_vintage(_provisional_vintage((2018, 6, 14)))
    use_case = VerifyPolicyRateReleaseTiming(repository=fake)

    report = await use_case("USD", SERIES_KEY)

    assert report.total_change_points == 1
    [cp] = report.change_points
    assert cp.outcome is ChangePointOutcome.EXACT
    assert cp.newly_applied is True

    stored = await fake.observation_as_known_at(SERIES_KEY, _ts(2018, 6, 14), _ts(2099, 1, 1))
    assert stored is not None
    assert stored.released_at_is_verified is True
    assert stored.released_at_is_conservative_bound is False
    # FX-44H: released_at is the FOMC decision timestamp (2018-06-13, the
    # day BEFORE the stored effective date), not the stored date itself.
    assert stored.released_at.value == datetime(2018, 6, 13, 18, 0, 0, tzinfo=UTC)
    assert stored.effective_at is not None
    assert stored.effective_at.value == datetime(2018, 6, 14, 0, 0, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_regular_pre_2013_date_is_newly_classified_conservative() -> None:
    fake = FakeMacroObservationRepository()
    await fake.add_vintage(_provisional_vintage((1994, 2, 4)))
    use_case = VerifyPolicyRateReleaseTiming(repository=fake)

    report = await use_case("USD", SERIES_KEY)

    [cp] = report.change_points
    assert cp.outcome is ChangePointOutcome.CONSERVATIVE_SAFE
    assert cp.newly_applied is True

    stored = await fake.observation_as_known_at(SERIES_KEY, _ts(1994, 2, 4), _ts(2099, 1, 1))
    assert stored is not None
    assert stored.released_at_is_verified is False
    assert stored.released_at_is_conservative_bound is True


@pytest.mark.asyncio
async def test_known_irregular_date_remains_provisional() -> None:
    # FX-44 test requirement: unresolved observation remains provisional.
    fake = FakeMacroObservationRepository()
    original = _provisional_vintage((2008, 1, 22))  # inter-meeting emergency cut
    await fake.add_vintage(original)
    use_case = VerifyPolicyRateReleaseTiming(repository=fake)

    report = await use_case("USD", SERIES_KEY)

    [cp] = report.change_points
    assert cp.outcome is ChangePointOutcome.UNRESOLVED
    assert cp.newly_applied is False

    stored = await fake.observation_as_known_at(SERIES_KEY, _ts(2008, 1, 22), _ts(2099, 1, 1))
    assert stored is not None
    assert stored.released_at_is_verified is False
    assert stored.released_at_is_conservative_bound is False
    assert stored.released_at == original.released_at  # untouched


@pytest.mark.asyncio
async def test_rerun_does_not_rewrite_an_already_classified_timestamp() -> None:
    # FX-44 test requirement: rerun does not rewrite an already-verified
    # timestamp.
    fake = FakeMacroObservationRepository()
    await fake.add_vintage(_provisional_vintage((2018, 6, 14)))
    use_case = VerifyPolicyRateReleaseTiming(repository=fake)

    first = await use_case("USD", SERIES_KEY)
    [first_cp] = first.change_points
    assert first_cp.newly_applied is True

    second = await use_case("USD", SERIES_KEY)
    [second_cp] = second.change_points
    assert second_cp.outcome is ChangePointOutcome.EXACT
    assert second_cp.newly_applied is False  # no-op, not an error

    stored = await fake.observation_as_known_at(SERIES_KEY, _ts(2018, 6, 14), _ts(2099, 1, 1))
    assert stored is not None
    assert stored.released_at.value == datetime(2018, 6, 13, 18, 0, 0, tzinfo=UTC)  # unchanged


@pytest.mark.asyncio
async def test_announcement_before_effective_date_for_eur() -> None:
    # FX-44 test requirement: announcement before effective date.
    fake = FakeMacroObservationRepository()
    eur_series_key = "EUR_POLICY_RATE"
    await fake.add_vintage(_provisional_vintage((2022, 7, 27), series_key=eur_series_key))
    use_case = VerifyPolicyRateReleaseTiming(repository=fake)

    report = await use_case("EUR", eur_series_key)

    [cp] = report.change_points
    assert cp.outcome is ChangePointOutcome.EXACT

    stored = await fake.observation_as_known_at(eur_series_key, _ts(2022, 7, 27), _ts(2099, 1, 1))
    assert stored is not None
    assert stored.effective_at is not None
    assert stored.released_at.value < stored.effective_at.value
    assert stored.released_at.value == datetime(2022, 7, 21, 12, 15, 0, tzinfo=UTC)
    assert stored.effective_at.value == datetime(2022, 7, 27, 0, 0, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_report_aggregates_across_mixed_outcomes() -> None:
    fake = FakeMacroObservationRepository()
    await fake.add_vintage(_provisional_vintage((2018, 6, 14)))  # exact
    await fake.add_vintage(_provisional_vintage((1994, 2, 4)))  # conservative
    await fake.add_vintage(_provisional_vintage((2008, 1, 22)))  # unresolved
    use_case = VerifyPolicyRateReleaseTiming(repository=fake)

    report = await use_case("USD", SERIES_KEY)

    assert report.total_change_points == 3
    assert len(report.exact_verified) == 1
    assert len(report.conservative_safe) == 1
    assert len(report.unresolved) == 1
    assert len(report.conflicting) == 0
    assert report.earliest_research_safe_date == _ts(1994, 2, 4)
    assert report.latest_research_safe_date == _ts(2018, 6, 14)


@pytest.mark.asyncio
async def test_a_future_timestamp_cannot_become_visible_before_its_release_time() -> None:
    # FX-44 test requirement: a future timestamp can never become
    # visible before its release time -- re-confirms the FX-41
    # point-in-time invariant still holds after a release-timing
    # correction moves released_at to a genuinely different instant.
    fake = FakeMacroObservationRepository()
    await fake.add_vintage(_provisional_vintage((2018, 6, 14)))
    use_case = VerifyPolicyRateReleaseTiming(repository=fake)
    await use_case("USD", SERIES_KEY)  # corrects released_at to 2018-06-13T18:00:00Z

    just_before = await fake.observation_as_known_at(
        SERIES_KEY, _ts(2018, 6, 14), UtcTimestamp(datetime(2018, 6, 13, 17, 59, 59, tzinfo=UTC))
    )
    at_release = await fake.observation_as_known_at(
        SERIES_KEY, _ts(2018, 6, 14), UtcTimestamp(datetime(2018, 6, 13, 18, 0, 0, tzinfo=UTC))
    )

    assert just_before is None  # not yet knowable, one second before release
    assert at_release is not None  # knowable exactly at release
