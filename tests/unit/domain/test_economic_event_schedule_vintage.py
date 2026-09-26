from datetime import UTC, date, datetime, time

import pytest

from forex_agent.domain.availability_confidence import AvailabilityConfidence
from forex_agent.domain.economic_event_schedule_vintage import EconomicEventScheduleVintage
from forex_agent.domain.economic_event_status import EconomicEventStatus
from forex_agent.domain.timestamps import UtcTimestamp

_AVAIL = UtcTimestamp(datetime(2026, 7, 1, tzinfo=UTC))


def _vintage(**overrides: object) -> EconomicEventScheduleVintage:
    defaults: dict[str, object] = {
        "occurrence_key": "US_CPI_2026_08",
        "revision_sequence": 0,
        "scheduled_date": date(2026, 8, 12),
        "scheduled_time": time(8, 30),
        "schedule_timezone": "America/New_York",
        "status": EconomicEventStatus.SCHEDULED,
        "availability": _AVAIL,
        "availability_confidence": AvailabilityConfidence.VERIFIED,
        "source": "test",
    }
    defaults.update(overrides)
    return EconomicEventScheduleVintage(**defaults)  # type: ignore[arg-type]


def test_time_unknown_is_represented_as_none_not_fabricated() -> None:
    vintage = _vintage(scheduled_time=None)
    assert vintage.scheduled_time is None


def test_unknown_confidence_requires_none_availability() -> None:
    with pytest.raises(ValueError, match="availability"):
        _vintage(availability=_AVAIL, availability_confidence=AvailabilityConfidence.UNKNOWN)


def test_verified_confidence_requires_availability() -> None:
    with pytest.raises(ValueError, match="availability"):
        _vintage(availability=None, availability_confidence=AvailabilityConfidence.VERIFIED)


def test_unknown_confidence_with_none_availability_is_valid() -> None:
    vintage = _vintage(availability=None, availability_confidence=AvailabilityConfidence.UNKNOWN)
    assert vintage.availability is None


def test_rejects_invalid_timezone_name() -> None:
    with pytest.raises(Exception):  # noqa: B017 -- ZoneInfoNotFoundError, not a project type
        _vintage(schedule_timezone="Not/A_Real_Zone")


def test_rejects_blank_occurrence_key() -> None:
    with pytest.raises(ValueError, match="occurrence_key"):
        _vintage(occurrence_key="")


def test_rejects_negative_revision_sequence() -> None:
    with pytest.raises(ValueError, match="revision_sequence"):
        _vintage(revision_sequence=-1)


def test_rejects_wrong_status_type() -> None:
    with pytest.raises(TypeError, match="status"):
        _vintage(status="CANCELLED")


def test_is_frozen() -> None:
    vintage = _vintage()
    with pytest.raises(AttributeError):
        vintage.status = EconomicEventStatus.CANCELLED  # type: ignore[misc]
