from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.domain.availability_confidence import AvailabilityConfidence
from forex_agent.domain.economic_event_actual_value_vintage import (
    EconomicEventActualValueVintage,
)
from forex_agent.domain.timestamps import UtcTimestamp

_REF = UtcTimestamp(datetime(2026, 8, 1, tzinfo=UTC))
_AVAIL = UtcTimestamp(datetime(2026, 9, 1, tzinfo=UTC))


def _vintage(**overrides: object) -> EconomicEventActualValueVintage:
    defaults: dict[str, object] = {
        "indicator_key": "US_NONFARM_PAYROLLS",
        "reference_period": _REF,
        "revision_sequence": 0,
        "actual_value": Decimal("150"),
        "availability": _AVAIL,
        "availability_confidence": AvailabilityConfidence.VERIFIED,
        "source": "test",
    }
    defaults.update(overrides)
    return EconomicEventActualValueVintage(**defaults)  # type: ignore[arg-type]


def test_rejects_float_actual_value() -> None:
    with pytest.raises(TypeError, match="actual_value"):
        _vintage(actual_value=150.0)


def test_backfill_with_unknown_availability_is_representable() -> None:
    backfilled = _vintage(availability=None, availability_confidence=AvailabilityConfidence.UNKNOWN)
    assert backfilled.availability is None
    assert backfilled.availability_confidence is AvailabilityConfidence.UNKNOWN


def test_estimated_confidence_requires_a_timestamp() -> None:
    with pytest.raises(ValueError, match="availability"):
        _vintage(availability=None, availability_confidence=AvailabilityConfidence.ESTIMATED)


def test_first_release_and_revision_are_distinct_immutable_rows() -> None:
    first = _vintage(revision_sequence=0, actual_value=Decimal("150"))
    revision = _vintage(revision_sequence=1, actual_value=Decimal("140"))
    assert first.actual_value == Decimal("150")
    assert revision.actual_value == Decimal("140")
    assert first != revision


def test_has_no_previous_value_field() -> None:
    """FX-51's own explicit design decision (Section 6/7): 'previous'
    and 'surprise' are deliberately NOT stored fields -- this test
    exists to catch an accidental future addition of either without a
    deliberate design decision to reopen this question."""
    vintage = _vintage()
    field_names = set(vintage.__dataclass_fields__)
    assert "previous_value" not in field_names
    assert "surprise" not in field_names
