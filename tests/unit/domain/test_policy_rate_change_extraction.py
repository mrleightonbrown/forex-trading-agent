from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.domain.policy_rate_change_extraction import (
    ConflictingRawObservationError,
    ExtractedPolicyRateChange,
    extract_change_points,
)
from forex_agent.domain.rate_transformation import RateTransformation, RateTransformationKind
from forex_agent.domain.timestamps import UtcTimestamp

_IDENTITY = RateTransformation(
    kind=RateTransformationKind.IDENTITY, version="v1", description="raw value used as-is"
)
_MIDPOINT = RateTransformation(
    kind=RateTransformationKind.TARGET_RANGE_MIDPOINT,
    version="v1",
    description="mean of upper/lower",
)


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


def _daily(*pairs: tuple[tuple[int, int, int], str]) -> tuple[tuple[UtcTimestamp, Decimal], ...]:
    return tuple((_ts(*date), Decimal(value)) for date, value in pairs)


def test_empty_raw_series_tuple_is_rejected() -> None:
    with pytest.raises(ValueError, match="raw_series"):
        extract_change_points((), _IDENTITY)


def test_single_series_all_repeated_values_yields_one_change_point() -> None:
    # The defining anti-interpolation guarantee: a provider's daily series
    # that just repeats the same value every day must NOT become five
    # "observations" -- only the first date counts as a change.
    series = _daily(
        ((2020, 1, 1), "1.75"),
        ((2020, 1, 2), "1.75"),
        ((2020, 1, 3), "1.75"),
        ((2020, 1, 4), "1.75"),
        ((2020, 1, 5), "1.75"),
    )

    result = extract_change_points((series,), _IDENTITY)

    assert result.changes == (ExtractedPolicyRateChange(_ts(2020, 1, 1), Decimal("1.75")),)
    assert result.skipped_dates == ()


def test_single_series_detects_each_genuine_change() -> None:
    series = _daily(
        ((2020, 1, 1), "1.75"),
        ((2020, 1, 2), "1.75"),
        ((2020, 1, 3), "2.00"),  # genuine change
        ((2020, 1, 4), "2.00"),
        ((2020, 1, 5), "1.50"),  # genuine change
    )

    result = extract_change_points((series,), _IDENTITY)

    assert result.changes == (
        ExtractedPolicyRateChange(_ts(2020, 1, 1), Decimal("1.75")),
        ExtractedPolicyRateChange(_ts(2020, 1, 3), Decimal("2.00")),
        ExtractedPolicyRateChange(_ts(2020, 1, 5), Decimal("1.50")),
    )


def test_out_of_order_and_duplicate_input_is_sorted_and_collapsed() -> None:
    # A provider adapter should never hand this function unsorted or
    # duplicate rows, but the function does not trust that blindly --
    # an identical-value duplicate collapses harmlessly (FX-43H), and
    # dates are processed in sorted order regardless of input order.
    series = (
        (_ts(2020, 1, 3), Decimal("2.00")),
        (_ts(2020, 1, 1), Decimal("1.75")),
        (_ts(2020, 1, 1), Decimal("1.75")),  # duplicate, same value -- harmless
    )

    result = extract_change_points((series,), _IDENTITY)

    assert result.changes == (
        ExtractedPolicyRateChange(_ts(2020, 1, 1), Decimal("1.75")),
        ExtractedPolicyRateChange(_ts(2020, 1, 3), Decimal("2.00")),
    )


def test_conflicting_duplicate_raw_values_on_one_date_raises() -> None:
    # FX-43H data-integrity rule: never "last value wins" -- two different
    # values for the same date within one raw series is a genuine
    # data-integrity error, not something to silently resolve.
    series = (
        (_ts(2020, 1, 1), Decimal("1.75")),
        (_ts(2020, 1, 1), Decimal("2.00")),  # same date, DIFFERENT value
    )

    with pytest.raises(ConflictingRawObservationError) as excinfo:
        extract_change_points((series,), _IDENTITY)

    assert excinfo.value.date == _ts(2020, 1, 1)
    assert {excinfo.value.first_value, excinfo.value.second_value} == {
        Decimal("1.75"),
        Decimal("2.00"),
    }


def test_conflicting_duplicate_raw_values_regardless_of_input_order() -> None:
    # Order-independence: the conflict is detected whichever value
    # appears first in the raw (unsorted) input.
    series = (
        (_ts(2020, 1, 1), Decimal("2.00")),
        (_ts(2020, 1, 1), Decimal("1.75")),
    )

    with pytest.raises(ConflictingRawObservationError):
        extract_change_points((series,), _IDENTITY)


def test_two_series_range_midpoint_detects_change_in_either_bound() -> None:
    upper = _daily(((2020, 1, 1), "0.50"), ((2020, 1, 2), "0.50"), ((2020, 1, 3), "0.75"))
    lower = _daily(((2020, 1, 1), "0.25"), ((2020, 1, 2), "0.25"), ((2020, 1, 3), "0.25"))

    result = extract_change_points((upper, lower), _MIDPOINT)

    assert result.changes == (
        ExtractedPolicyRateChange(_ts(2020, 1, 1), Decimal("0.375")),
        ExtractedPolicyRateChange(_ts(2020, 1, 3), Decimal("0.500")),
    )


def test_date_missing_from_one_series_is_skipped_not_fabricated() -> None:
    # No synthetic interpolation: a date present in the upper-bound series
    # but absent from the lower-bound series must never be paired with a
    # guessed lower value -- it is skipped and reported, not filled in.
    upper = _daily(((2020, 1, 1), "0.50"), ((2020, 1, 2), "0.50"))
    lower = _daily(((2020, 1, 1), "0.25"))  # 2020-01-02 missing

    result = extract_change_points((upper, lower), _MIDPOINT)

    assert result.changes == (ExtractedPolicyRateChange(_ts(2020, 1, 1), Decimal("0.375")),)
    assert result.skipped_dates == (_ts(2020, 1, 2),)


def test_no_change_points_when_every_date_is_skipped() -> None:
    upper = _daily(((2020, 1, 1), "0.50"))
    lower = _daily(((2020, 1, 2), "0.25"))  # disjoint dates entirely

    result = extract_change_points((upper, lower), _MIDPOINT)

    assert result.changes == ()
    assert set(result.skipped_dates) == {_ts(2020, 1, 1), _ts(2020, 1, 2)}


def test_single_empty_series_yields_no_changes() -> None:
    result = extract_change_points(((),), _IDENTITY)

    assert result.changes == ()
    assert result.skipped_dates == ()
