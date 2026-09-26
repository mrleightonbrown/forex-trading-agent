from datetime import UTC, datetime

import pytest

from forex_agent.domain.economic_event_occurrence import EconomicEventOccurrence
from forex_agent.domain.timestamps import UtcTimestamp

_REF = UtcTimestamp(datetime(2026, 8, 1, tzinfo=UTC))


def test_release_group_key_defaults_to_none() -> None:
    occurrence = EconomicEventOccurrence(indicator_key="US_CPI_YOY", reference_period=_REF)
    assert occurrence.release_group_key is None


def test_release_group_key_can_be_shared() -> None:
    headline = EconomicEventOccurrence(
        indicator_key="US_CPI_YOY", reference_period=_REF, release_group_key="US_CPI_2026_08"
    )
    core = EconomicEventOccurrence(
        indicator_key="US_CPI_CORE_YOY", reference_period=_REF, release_group_key="US_CPI_2026_08"
    )
    assert headline.release_group_key == core.release_group_key
    assert headline.indicator_key != core.indicator_key


def test_rejects_blank_indicator_key() -> None:
    with pytest.raises(ValueError, match="indicator_key"):
        EconomicEventOccurrence(indicator_key="", reference_period=_REF)


def test_rejects_blank_release_group_key() -> None:
    with pytest.raises(ValueError, match="release_group_key"):
        EconomicEventOccurrence(
            indicator_key="US_CPI_YOY", reference_period=_REF, release_group_key="  "
        )


def test_rejects_non_utctimestamp_reference_period() -> None:
    with pytest.raises(TypeError, match="reference_period"):
        EconomicEventOccurrence(
            indicator_key="US_CPI_YOY",
            reference_period=datetime(2026, 8, 1, tzinfo=UTC),  # type: ignore[arg-type]
        )
