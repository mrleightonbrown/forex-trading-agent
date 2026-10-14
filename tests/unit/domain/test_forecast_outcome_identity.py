"""FX-65H.2: tests for `canonical_target_period_key` and
`ForecastOutcomeIdentityBinding`."""

from datetime import UTC, datetime

import pytest

from forex_agent.domain.forecast_outcome_identity import (
    NO_UNIT_SENTINEL,
    ForecastOutcomeIdentityBinding,
    canonical_target_period_key,
)
from forex_agent.domain.forecast_target_period import ForecastTargetPeriod
from forex_agent.domain.forecast_target_period_kind import ForecastTargetPeriodKind
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.timestamps import UtcTimestamp


def test_calendar_year_key() -> None:
    period = ForecastTargetPeriod(
        period_kind=ForecastTargetPeriodKind.CALENDAR_YEAR, calendar_year=2025
    )
    assert canonical_target_period_key(period) == "CALENDAR_YEAR:2025"


def test_calendar_quarter_key() -> None:
    period = ForecastTargetPeriod(
        period_kind=ForecastTargetPeriodKind.CALENDAR_QUARTER,
        calendar_year=2025,
        calendar_quarter=2,
    )
    assert canonical_target_period_key(period) == "CALENDAR_QUARTER:2025:2"


def test_calendar_month_key_is_zero_padded() -> None:
    period = ForecastTargetPeriod(
        period_kind=ForecastTargetPeriodKind.CALENDAR_MONTH, calendar_year=2025, calendar_month=3
    )
    assert canonical_target_period_key(period) == "CALENDAR_MONTH:2025:03"


def test_specific_date_key_with_zero_microseconds_is_fixed_width() -> None:
    """FX-65H.3 (H3): the microsecond component is UNCONDITIONALLY
    present, even when zero -- `datetime.isoformat()` alone would
    omit it here, which is exactly the Python/SQL parity break this
    story fixed (the migration's own SQL always produces 6 digits)."""
    period = ForecastTargetPeriod(
        period_kind=ForecastTargetPeriodKind.SPECIFIC_DATE,
        specific_date=UtcTimestamp(datetime(2025, 1, 15, tzinfo=UTC)),
    )
    assert canonical_target_period_key(period) == "SPECIFIC_DATE:2025-01-15T00:00:00.000000+00:00"


def test_specific_date_key_preserves_microsecond_precision() -> None:
    period = ForecastTargetPeriod(
        period_kind=ForecastTargetPeriodKind.SPECIFIC_DATE,
        specific_date=UtcTimestamp(datetime(2024, 12, 11, 12, 30, 45, 654321, tzinfo=UTC)),
    )
    assert canonical_target_period_key(period) == "SPECIFIC_DATE:2024-12-11T12:30:45.654321+00:00"


def test_specific_date_keys_differing_only_by_microsecond_are_distinct() -> None:
    a = ForecastTargetPeriod(
        period_kind=ForecastTargetPeriodKind.SPECIFIC_DATE,
        specific_date=UtcTimestamp(datetime(2024, 12, 11, 0, 0, 0, 1, tzinfo=UTC)),
    )
    b = ForecastTargetPeriod(
        period_kind=ForecastTargetPeriodKind.SPECIFIC_DATE,
        specific_date=UtcTimestamp(datetime(2024, 12, 11, 0, 0, 0, tzinfo=UTC)),
    )
    assert canonical_target_period_key(a) != canonical_target_period_key(b)


def test_policy_meeting_key() -> None:
    period = ForecastTargetPeriod(
        period_kind=ForecastTargetPeriodKind.POLICY_MEETING,
        policy_meeting_identifier="BOC-2024-12-11",
    )
    assert canonical_target_period_key(period) == "POLICY_MEETING:BOC-2024-12-11"


def test_different_meetings_produce_different_keys() -> None:
    a = ForecastTargetPeriod(
        period_kind=ForecastTargetPeriodKind.POLICY_MEETING,
        policy_meeting_identifier="BOC-2024-12-11",
    )
    b = ForecastTargetPeriod(
        period_kind=ForecastTargetPeriodKind.POLICY_MEETING,
        policy_meeting_identifier="BOC-2025-01-29",
    )
    assert canonical_target_period_key(a) != canonical_target_period_key(b)


def _binding(**overrides: object) -> ForecastOutcomeIdentityBinding:
    defaults: dict[str, object] = {
        "definition_key": "BOC-RATE-OUTCOME",
        "target_period_key": "POLICY_MEETING:BOC-2024-12-11",
        "outcome_type": ForecastType.NUMERIC_POINT,
        "unit": "PERCENT",
        "outcome_key": "BOC-RATE-DECISION-2024-12-11",
    }
    defaults.update(overrides)
    return ForecastOutcomeIdentityBinding(**defaults)  # type: ignore[arg-type]


def test_shares_identity_with_ignores_outcome_key() -> None:
    a = _binding(outcome_key="KEY-A")
    b = _binding(outcome_key="KEY-B")

    assert a.shares_identity_with(b) is True


def test_shares_identity_with_detects_unit_difference() -> None:
    a = _binding(unit="PERCENT")
    b = _binding(unit=NO_UNIT_SENTINEL)

    assert a.shares_identity_with(b) is False


def test_empty_definition_key_rejected() -> None:
    with pytest.raises(ValueError, match="definition_key"):
        _binding(definition_key="")


def test_non_forecast_type_rejected() -> None:
    with pytest.raises(TypeError, match="outcome_type"):
        _binding(outcome_type="NUMERIC_POINT")
