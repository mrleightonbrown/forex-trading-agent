from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.domain.availability_confidence import AvailabilityConfidence
from forex_agent.domain.economic_event_consensus_vintage import EconomicEventConsensusVintage
from forex_agent.domain.timestamps import UtcTimestamp

_AVAIL = UtcTimestamp(datetime(2026, 7, 1, tzinfo=UTC))


def _vintage(**overrides: object) -> EconomicEventConsensusVintage:
    defaults: dict[str, object] = {
        "occurrence_key": "US_CPI_2026_08",
        "revision_sequence": 0,
        "consensus_value": Decimal("3.1"),
        "availability": _AVAIL,
        "availability_confidence": AvailabilityConfidence.VERIFIED,
        "source": "test",
    }
    defaults.update(overrides)
    return EconomicEventConsensusVintage(**defaults)  # type: ignore[arg-type]


def test_rejects_float_consensus_value() -> None:
    with pytest.raises(TypeError, match="consensus_value"):
        _vintage(consensus_value=3.1)


def test_unknown_confidence_requires_none_availability() -> None:
    with pytest.raises(ValueError, match="availability"):
        _vintage(availability=_AVAIL, availability_confidence=AvailabilityConfidence.UNKNOWN)


def test_raw_source_value_optional_and_preserved() -> None:
    vintage = _vintage(raw_source_value="3.1%")
    assert vintage.raw_source_value == "3.1%"
    assert _vintage().raw_source_value is None


def test_rejects_negative_revision_sequence() -> None:
    with pytest.raises(ValueError, match="revision_sequence"):
        _vintage(revision_sequence=-1)


def test_rejects_blank_occurrence_key() -> None:
    with pytest.raises(ValueError, match="occurrence_key"):
        _vintage(occurrence_key="")


def test_two_vintages_same_identity_different_value_are_not_equal() -> None:
    first = _vintage(revision_sequence=0, consensus_value=Decimal("3.1"))
    revised = _vintage(revision_sequence=1, consensus_value=Decimal("3.0"))
    assert first != revised
