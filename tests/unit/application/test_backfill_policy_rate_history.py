"""FX-43: `BackfillPolicyRateHistory` tests. FX-43H: half-open era
boundary enforcement, raw-vs-change-point coverage separation,
inserted/already-present reporting, and conflicting-raw-value
data-integrity reporting. Uses the REAL policy-rate registry (matching
how `AggregateCandles` et al. call domain functions directly, not
through an injected port) with FAKE provider data keyed to the
registry's own real `provider_series_ids` -- exercising real registry
wiring without touching a network.
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
    assert range_era.vintages_inserted == 2
    assert range_era.vintages_already_present == 0
    assert range_era.conflicts == ()
    assert range_era.fetch_error is None
    assert range_era.data_integrity_error is None
    assert range_era.earliest_change_point == _ts(2020, 1, 1)
    assert range_era.latest_change_point == _ts(2020, 1, 6)
    assert range_era.earliest_raw_observation == _ts(2020, 1, 1)
    assert range_era.latest_raw_observation == _ts(2020, 1, 7)


@pytest.mark.asyncio
async def test_ingested_vintages_are_marked_provisional() -> None:
    # FX-43H: released_at is an effective-date proxy, not a confirmed
    # announcement timestamp -- every vintage this use case writes must
    # say so explicitly, so nothing downstream can mistake it for a
    # verified timestamp.
    repository = FakeMacroObservationRepository()
    use_case = BackfillPolicyRateHistory(
        providers={"FRED": _fred_with_a_hike()}, repository=repository
    )

    await use_case("USD", _ts(2020, 1, 7))

    stored = await repository.observation_as_known_at(
        "USD_POLICY_RATE", _ts(2020, 1, 1), _ts(2020, 1, 5)
    )
    assert stored is not None
    assert stored.released_at_is_verified is False


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
async def test_coverage_end_reflects_raw_data_not_last_change_point() -> None:
    # FX-43H's own required scenario: the final policy change occurs
    # months before the final raw observation (a stable rate keeps being
    # published daily with no further change) -- coverage_end must be the
    # raw observation date, not the change-point date.
    stable_after_change = [
        (_ts(2010, 1, 1), Decimal("1.00")),
        (_ts(2010, 2, 1), Decimal("1.25")),  # the last genuine change
        (_ts(2010, 3, 1), Decimal("1.25")),  # unchanged, still published
        (_ts(2010, 4, 1), Decimal("1.25")),
        (_ts(2010, 5, 1), Decimal("1.25")),
        (_ts(2010, 6, 1), Decimal("1.25")),  # months later, still stable
    ]
    provider = FakePolicyRateHistoryProvider({"IUDBEDR": stable_after_change})
    use_case = BackfillPolicyRateHistory(
        providers={"BOE_DATABASE": provider}, repository=FakeMacroObservationRepository()
    )

    report = await use_case("GBP", _ts(2020, 1, 1))

    range_era = next(e for e in report.eras if e.change_points_found > 0)
    assert range_era.latest_change_point == _ts(2010, 2, 1)
    assert range_era.latest_raw_observation == _ts(2010, 6, 1)
    assert range_era.latest_change_point != range_era.latest_raw_observation
    # And the currency-level summary must reflect the RAW span, not the
    # narrower change-point span.
    assert report.coverage_end == _ts(2010, 6, 1)


@pytest.mark.asyncio
async def test_backfill_is_idempotent_on_rerun() -> None:
    # The critical acceptance point: running the exact same backfill twice
    # must not duplicate or error, and must report an accurate
    # inserted/already-present split -- not just "no crash".
    repository = FakeMacroObservationRepository()
    use_case = BackfillPolicyRateHistory(
        providers={"FRED": _fred_with_a_hike()}, repository=repository
    )

    first = await use_case("USD", _ts(2020, 1, 7))
    second = await use_case("USD", _ts(2020, 1, 7))

    first_range_era = next(e for e in first.eras if e.change_points_found > 0)
    second_range_era = next(e for e in second.eras if e.change_points_found > 0)
    assert first_range_era.vintages_inserted == 2
    assert first_range_era.vintages_already_present == 0
    assert second_range_era.vintages_inserted == 0
    assert second_range_era.vintages_already_present == 2
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
    assert report.total_vintages_inserted == 0
    assert report.total_vintages_already_present == 0
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
    assert failed_era.vintages_inserted == 0
    assert failed_era.vintages_already_present == 0


@pytest.mark.asyncio
async def test_conflicting_raw_values_are_reported_as_data_integrity_error() -> None:
    # FX-43H: two different raw values for the same date must never be
    # resolved by "last value wins" -- the era is reported with an
    # explicit data_integrity_error and zero vintages written, not a
    # crash and not silently-wrong data.
    conflicting_upper = [
        (_ts(2020, 1, 1), Decimal("1.75")),
        (_ts(2020, 1, 1), Decimal("2.00")),  # same date, different value
    ]
    lower = [(_ts(2020, 1, 1), Decimal("1.50"))]
    provider = FakePolicyRateHistoryProvider({"DFEDTARU": conflicting_upper, "DFEDTARL": lower})
    use_case = BackfillPolicyRateHistory(
        providers={"FRED": provider}, repository=FakeMacroObservationRepository()
    )

    report = await use_case("USD", _ts(2020, 1, 7))

    range_era = next(
        e for e in report.eras if e.provider == "FRED" and "DFEDTARU" in e.provider_series_ids
    )
    assert range_era.data_integrity_error is not None
    assert "conflicting raw observations" in range_era.data_integrity_error
    assert range_era.vintages_inserted == 0
    assert range_era.vintages_already_present == 0
    assert range_era.change_points_found == 0


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
    assert report.total_vintages_inserted == 0


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


@pytest.mark.asyncio
async def test_half_open_era_boundary_is_enforced_against_the_provider_fetch() -> None:
    # The story's own required scenario: era A's valid_to and era B's
    # valid_from are the SAME date D, and BOTH providers report a row on
    # D. D must belong ONLY to era B -- era A's fetch must never even
    # request D, regardless of what era A's own provider happens to
    # return for it.
    #
    # USD's real registry boundary: the target-point era's valid_to and
    # the target-range era's valid_from are both 2008-12-16.
    boundary = _ts(2008, 12, 16)
    day_before = _ts(2008, 12, 15)

    # Era A (target-point, DFEDTAR) -- deliberately includes a row AT the
    # boundary date, contrary to real FRED behavior (which happens to
    # stop the day before) -- this is exactly the "do not rely on
    # provider behavior" case the story calls out.
    target_point_data = [
        (day_before, Decimal("1.0000")),
        (boundary, Decimal("99.9999")),  # must NEVER be fetched by era A
    ]
    # Era B (target-range, DFEDTARU/DFEDTARL) -- also has a row on the
    # boundary date, which correctly belongs to it.
    target_range_upper = [(boundary, Decimal("0.25"))]
    target_range_lower = [(boundary, Decimal("0.00"))]

    provider = FakePolicyRateHistoryProvider(
        {
            "DFEDTAR": target_point_data,
            "DFEDTARU": target_range_upper,
            "DFEDTARL": target_range_lower,
        }
    )
    use_case = BackfillPolicyRateHistory(
        providers={"FRED": provider}, repository=FakeMacroObservationRepository()
    )

    report = await use_case("USD", boundary)

    target_point_era = next(e for e in report.eras if e.provider_series_ids == ("DFEDTAR",))
    target_range_era = next(
        e for e in report.eras if e.provider_series_ids == ("DFEDTARU", "DFEDTARL")
    )

    # Era A's fetch window must have been clamped BEFORE the boundary --
    # its own requested_end must not reach the boundary date at all.
    assert target_point_era.requested_end.value < boundary.value
    # ... and consequently it never saw the boundary row, so its latest
    # raw observation is the day before, not the (fabricated, wrong)
    # boundary-date value.
    assert target_point_era.latest_raw_observation == day_before

    # Era B correctly owns the boundary date.
    assert target_range_era.requested_start == boundary
    assert target_range_era.change_points_found == 1
    assert target_range_era.earliest_change_point == boundary

    # No conflict anywhere -- the boundary date was never fought over.
    assert target_point_era.conflicts == ()
    assert target_range_era.conflicts == ()
