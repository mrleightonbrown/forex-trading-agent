from datetime import UTC, date, datetime, time

import pytest

from forex_agent.domain.availability_confidence import AvailabilityConfidence
from forex_agent.domain.economic_event_actual_value_vintage import (
    EconomicEventActualValueVintage,
)
from forex_agent.domain.economic_event_release_vintage import EconomicEventReleaseVintage
from forex_agent.domain.timestamps import UtcTimestamp

_AVAIL = UtcTimestamp(datetime(2026, 9, 4, 13, 35, tzinfo=UTC))


def _vintage(**overrides: object) -> EconomicEventReleaseVintage:
    defaults: dict[str, object] = {
        "occurrence_key": "US_NFP_2026_08",
        "revision_sequence": 0,
        "released_date": date(2026, 9, 4),
        "released_time": time(13, 30),
        "released_timezone": "UTC",
        "availability": _AVAIL,
        "availability_confidence": AvailabilityConfidence.VERIFIED,
        "source": "test",
    }
    defaults.update(overrides)
    return EconomicEventReleaseVintage(**defaults)  # type: ignore[arg-type]


def test_released_at_and_availability_are_independent_instants() -> None:
    # FX-51H Section 2's own central distinction: a release can happen
    # at one instant and only become knowable to the system later.
    vintage = _vintage(
        released_date=date(2026, 9, 4),
        released_time=time(13, 30),
        released_timezone="UTC",
        availability=UtcTimestamp(datetime(2026, 9, 6, 9, 0, tzinfo=UTC)),
    )
    assert vintage.released_time is not None
    assert vintage.availability is not None
    released_instant = datetime.combine(vintage.released_date, vintage.released_time, tzinfo=UTC)
    assert released_instant < vintage.availability.value


def test_qualitative_event_can_record_a_release_without_a_numeric_value() -> None:
    # A central-bank press conference has no ActualValueVintage at all
    # (FX-51 Section 18) -- but it can still have a release fact.
    release = _vintage(occurrence_key="FOMC_PRESS_CONF_2026_09")
    assert release.occurrence_key == "FOMC_PRESS_CONF_2026_09"
    # Confirms this type carries no numeric-value field of its own.
    assert "actual_value" not in release.__dataclass_fields__


def test_released_time_unknown_is_represented_as_none_not_fabricated() -> None:
    vintage = _vintage(released_time=None)
    assert vintage.released_time is None


def test_unknown_confidence_requires_none_availability() -> None:
    with pytest.raises(ValueError, match="availability"):
        _vintage(availability=_AVAIL, availability_confidence=AvailabilityConfidence.UNKNOWN)


def test_verified_confidence_requires_availability() -> None:
    with pytest.raises(ValueError, match="availability"):
        _vintage(availability=None, availability_confidence=AvailabilityConfidence.VERIFIED)


def test_rejects_invalid_timezone_name() -> None:
    with pytest.raises(Exception):  # noqa: B017 -- ZoneInfoNotFoundError, not a project type
        _vintage(released_timezone="Not/A_Real_Zone")


def test_rejects_negative_revision_sequence() -> None:
    with pytest.raises(ValueError, match="revision_sequence"):
        _vintage(revision_sequence=-1)


def test_rejects_blank_occurrence_key() -> None:
    with pytest.raises(ValueError, match="occurrence_key"):
        _vintage(occurrence_key="")


def test_is_frozen() -> None:
    vintage = _vintage()
    with pytest.raises(AttributeError):
        vintage.released_date = date(2026, 9, 5)  # type: ignore[misc]


def test_distinct_type_from_actual_value_vintage() -> None:
    # Guards against ever conflating the two -- an actual-value vintage
    # carries a number and no released_date/time; a release vintage
    # carries released_date/time and no number.
    assert not issubclass(EconomicEventReleaseVintage, EconomicEventActualValueVintage)
    assert not issubclass(EconomicEventActualValueVintage, EconomicEventReleaseVintage)
