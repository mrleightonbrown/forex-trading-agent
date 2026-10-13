"""FX-64 Section 10: tests for `ForecastTargetPeriod` -- exactly the
fields matching `period_kind` must be populated, every other field
must be `None`."""

from datetime import UTC, datetime

import pytest

from forex_agent.domain.forecast_target_period import ForecastTargetPeriod
from forex_agent.domain.forecast_target_period_kind import ForecastTargetPeriodKind
from forex_agent.domain.timestamps import UtcTimestamp


def test_calendar_year_valid() -> None:
    period = ForecastTargetPeriod(
        period_kind=ForecastTargetPeriodKind.CALENDAR_YEAR, calendar_year=2025
    )
    assert period.calendar_year == 2025


def test_calendar_year_rejects_extra_fields() -> None:
    with pytest.raises(ValueError, match="calendar_quarter"):
        ForecastTargetPeriod(
            period_kind=ForecastTargetPeriodKind.CALENDAR_YEAR,
            calendar_year=2025,
            calendar_quarter=1,
        )


def test_calendar_year_missing_rejected() -> None:
    with pytest.raises(TypeError, match="calendar_year"):
        ForecastTargetPeriod(period_kind=ForecastTargetPeriodKind.CALENDAR_YEAR)


def test_calendar_quarter_valid() -> None:
    period = ForecastTargetPeriod(
        period_kind=ForecastTargetPeriodKind.CALENDAR_QUARTER,
        calendar_year=2025,
        calendar_quarter=2,
    )
    assert period.calendar_quarter == 2


def test_calendar_quarter_out_of_range_rejected() -> None:
    with pytest.raises(ValueError, match="calendar_quarter"):
        ForecastTargetPeriod(
            period_kind=ForecastTargetPeriodKind.CALENDAR_QUARTER,
            calendar_year=2025,
            calendar_quarter=5,
        )


def test_calendar_month_valid() -> None:
    period = ForecastTargetPeriod(
        period_kind=ForecastTargetPeriodKind.CALENDAR_MONTH,
        calendar_year=2025,
        calendar_month=12,
    )
    assert period.calendar_month == 12


def test_calendar_month_out_of_range_rejected() -> None:
    with pytest.raises(ValueError, match="calendar_month"):
        ForecastTargetPeriod(
            period_kind=ForecastTargetPeriodKind.CALENDAR_MONTH,
            calendar_year=2025,
            calendar_month=13,
        )


def test_specific_date_valid() -> None:
    date = UtcTimestamp(datetime(2026, 3, 15, tzinfo=UTC))
    period = ForecastTargetPeriod(
        period_kind=ForecastTargetPeriodKind.SPECIFIC_DATE, specific_date=date
    )
    assert period.specific_date == date


def test_specific_date_missing_rejected() -> None:
    with pytest.raises(TypeError, match="specific_date"):
        ForecastTargetPeriod(period_kind=ForecastTargetPeriodKind.SPECIFIC_DATE)


def test_policy_meeting_valid() -> None:
    period = ForecastTargetPeriod(
        period_kind=ForecastTargetPeriodKind.POLICY_MEETING,
        policy_meeting_identifier="BOC-2026-03-15",
    )
    assert period.policy_meeting_identifier == "BOC-2026-03-15"


def test_policy_meeting_empty_identifier_rejected() -> None:
    with pytest.raises(ValueError, match="policy_meeting_identifier"):
        ForecastTargetPeriod(
            period_kind=ForecastTargetPeriodKind.POLICY_MEETING, policy_meeting_identifier=""
        )


def test_policy_meeting_rejects_calendar_year() -> None:
    with pytest.raises(ValueError, match="calendar_year"):
        ForecastTargetPeriod(
            period_kind=ForecastTargetPeriodKind.POLICY_MEETING,
            policy_meeting_identifier="BOC-2026-03-15",
            calendar_year=2026,
        )


def test_wrong_period_kind_type_rejected() -> None:
    with pytest.raises(TypeError, match="period_kind"):
        ForecastTargetPeriod(period_kind="CALENDAR_YEAR", calendar_year=2025)  # type: ignore[arg-type]


def test_implausible_calendar_year_rejected() -> None:
    with pytest.raises(ValueError, match="implausible"):
        ForecastTargetPeriod(period_kind=ForecastTargetPeriodKind.CALENDAR_YEAR, calendar_year=11)
