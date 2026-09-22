"""FX-43: `BackfillPolicyRateHistory` tests. Uses the REAL policy-rate
registry (matching how `AggregateCandles` et al. call domain functions
directly, not through an injected port) with FAKE provider data keyed
to the registry's own real `provider_series_ids` -- exercising real
registry wiring without touching a network.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.application.ports.policy_rate_history_provider import (
    PolicyRateProviderUnavailableError,
)
from forex_agent.application.use_cases.backfill_policy_rate_history import (
    BackfillPolicyRateHistory,
)
from forex_agent.domain.timestamps import UtcTimestamp
from tests.fakes.macro_observation_repository import FakeMacroObservationRepository
from tests.fakes.policy_rate_history_provider import FakePolicyRateHistoryProvider


def _ts(*args: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(*args, tzinfo=UTC))


def _fred_with_a_hike() -> FakePolicyRateHistoryProvider:
    # A tiny synthetic slice of USD's target-range era: 1.75% through
    # 2020-01-05, hiked to 2.00% on 2020-01-06.
    upper = [
        (_ts(2020, 1, 1), Decimal("1.75")),
        (_ts(2020, 1, 2), Decimal("1.75")),
        (_ts(2020, 1, 3), Decimal("1.75")),
        (_ts(2020, 1, 4), Decimal("1.75")),
        (_ts(2020, 1, 5), Decimal("1.75")),
        (_ts(2020, 1, 6), Decimal("2.00")),
        (_ts(2020, 1, 7), Decimal("2.00")),
    ]
    lower = [(ts, value - Decimal("0.25")) for ts, value in upper]
    return FakePolicyRateHistoryProvider({"DFEDTARU": upper, "DFEDTARL": lower})


@pytest.mark.asyncio
async def test_backfill_extracts_change_points_and_ingests_vintages() -> None:
    use_case = BackfillPolicyRateHistory(
        providers={"FRED": _fred_with_a_hike()},
        repository=FakeMacroObservationRepository(),
    )

    report = await use_case("USD", _ts(2020, 1, 7))

    assert report.currency == "USD"
    assert report.series_key == "USD_POLICY_RATE"
    range_era = next(e for e in report.eras if e.provider == "FRED" and e.change_points_found > 0)
    # Two change points in the fake window: the initial 1.625 level on
    # 2020-01-01, and the hike to 1.875 on 2020-01-06 (midpoints of the
    # upper/lower pairs above).
    assert range_era.change_points_found == 2
    assert range_era.vintages_ingested == 2
    assert range_era.conflicts == ()
    assert range_era.fetch_error is None
    assert range_era.earliest_change_point == _ts(2020, 1, 1)
    assert range_era.latest_change_point == _ts(2020, 1, 6)


@pytest.mark.asyncio
async def test_coverage_reflects_actual_data_not_the_requested_window() -> None:
    # Found running FX-43's real backfill live: CAD's registry valid_from
    # is 1999-02-01, but its provider's real data only starts 2009-04-21.
    # coverage_start/coverage_end must reflect what was actually ingested,
    # not what was merely asked for -- otherwise the report would silently
    # overstate coverage for exactly this documented gap.
    late_starting_data = [
        (_ts(2010, 1, 1), Decimal("1.00")),
        (_ts(2010, 6, 1), Decimal("1.25")),
    ]
    provider = FakePolicyRateHistoryProvider({"IUDBEDR": late_starting_data})
    use_case = BackfillPolicyRateHistory(
        providers={"BOE_DATABASE": provider}, repository=FakeMacroObservationRepository()
    )

    # GBP's registry valid_from is 1997-06-01 -- materially earlier than
    # this fake provider's first real data point.
    report = await use_case("GBP", _ts(2020, 1, 1))

    assert report.coverage_start == _ts(2010, 1, 1)
    assert report.coverage_end == _ts(2010, 6, 1)
    assert report.coverage_start != _ts(1997, 6, 1)  # NOT the requested start


@pytest.mark.asyncio
async def test_backfill_is_idempotent_on_rerun() -> None:
    # The critical acceptance point: running the exact same backfill twice
    # must not duplicate or error.
    repository = FakeMacroObservationRepository()
    use_case = BackfillPolicyRateHistory(
        providers={"FRED": _fred_with_a_hike()}, repository=repository
    )

    first = await use_case("USD", _ts(2020, 1, 7))
    second = await use_case("USD", _ts(2020, 1, 7))

    first_range_era = next(e for e in first.eras if e.change_points_found > 0)
    second_range_era = next(e for e in second.eras if e.change_points_found > 0)
    assert first_range_era.vintages_ingested == second_range_era.vintages_ingested == 2
    assert second_range_era.conflicts == ()

    # Confirm no duplication at the repository level too, not just via the
    # use case's own reported counts.
    known_value = await repository.observation_as_known_at(
        "USD_POLICY_RATE", _ts(2020, 1, 1), _ts(2020, 1, 5)
    )
    assert known_value is not None
    assert known_value.value == Decimal("1.625")


@pytest.mark.asyncio
async def test_unconfigured_provider_is_reported_not_silently_skipped() -> None:
    # JPY's provider mapping remains entirely unresolved (FX-42H.1) -- no
    # provider supplied for it here should surface as an explicit
    # unconfigured era, never silently produce an empty-but-successful
    # report.
    use_case = BackfillPolicyRateHistory(providers={}, repository=FakeMacroObservationRepository())

    report = await use_case("JPY", _ts(2020, 1, 1))

    assert len(report.eras) > 0
    assert all(not era.provider_configured for era in report.eras)
    assert len(report.unconfigured_eras) == len(report.eras)
    assert report.total_vintages_ingested == 0
    assert report.coverage_start is None
    assert report.coverage_end is None


@pytest.mark.asyncio
async def test_provider_fetch_failure_is_reported_not_raised() -> None:
    class _AlwaysFailsProvider:
        async def fetch_daily_series(
            self, provider_series_id: str, start: UtcTimestamp, end: UtcTimestamp
        ) -> list[tuple[UtcTimestamp, Decimal]]:
            raise PolicyRateProviderUnavailableError("simulated network failure")

    use_case = BackfillPolicyRateHistory(
        providers={"FRED": _AlwaysFailsProvider()}, repository=FakeMacroObservationRepository()
    )

    report = await use_case("USD", _ts(2020, 1, 7))

    failed_era = next(e for e in report.eras if e.provider == "FRED")
    assert failed_era.provider_configured is True
    assert failed_era.fetch_error is not None
    assert failed_era.vintages_ingested == 0


@pytest.mark.asyncio
async def test_no_change_points_before_earliest_era_valid_from() -> None:
    use_case = BackfillPolicyRateHistory(
        providers={"FRED": _fred_with_a_hike()},
        repository=FakeMacroObservationRepository(),
    )

    # USD's earliest era starts 1994-02-04 -- an as_of before that leaves
    # nothing to backfill at all.
    report = await use_case("USD", _ts(1990, 1, 1))

    assert report.eras == ()
    assert report.total_vintages_ingested == 0


@pytest.mark.asyncio
async def test_only_eras_reached_by_as_of_are_attempted() -> None:
    use_case = BackfillPolicyRateHistory(
        providers={"FRED": _fred_with_a_hike()},
        repository=FakeMacroObservationRepository(),
    )

    # 2000-01-01 falls inside USD's pre-2008 target-point era -- the later
    # target-range era hasn't started yet and must not be attempted.
    report = await use_case("USD", _ts(2000, 1, 1))

    assert len(report.eras) == 1
    assert report.eras[0].instrument_name == "Federal Funds Target Rate (single target point)"
