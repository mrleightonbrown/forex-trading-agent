from datetime import UTC, datetime

import pytest

from forex_agent.domain.economic_event_occurrence import EconomicEventOccurrence
from forex_agent.domain.timestamps import UtcTimestamp

_REF = UtcTimestamp(datetime(2026, 8, 1, tzinfo=UTC))


def test_reference_period_defaults_to_none() -> None:
    occurrence = EconomicEventOccurrence(
        occurrence_key="US_CPI_2026_08", indicator_key="US_CPI_YOY"
    )
    assert occurrence.reference_period is None


def test_reference_period_can_be_set_for_a_periodic_release() -> None:
    occurrence = EconomicEventOccurrence(
        occurrence_key="US_CPI_2026_08", indicator_key="US_CPI_YOY", reference_period=_REF
    )
    assert occurrence.reference_period == _REF


def test_reference_period_none_for_a_qualitative_irregular_event() -> None:
    # A press conference or unscheduled statement is not "for" a
    # calendar period at all -- None is a genuine domain fact here,
    # not a placeholder (FX-51H Section 3).
    occurrence = EconomicEventOccurrence(
        occurrence_key="FOMC_PRESS_CONF_2026_09", indicator_key="FOMC_PRESS_CONFERENCE"
    )
    assert occurrence.reference_period is None


def test_release_group_key_defaults_to_none() -> None:
    occurrence = EconomicEventOccurrence(
        occurrence_key="US_CPI_2026_08", indicator_key="US_CPI_YOY"
    )
    assert occurrence.release_group_key is None


def test_release_group_key_can_be_shared() -> None:
    headline = EconomicEventOccurrence(
        occurrence_key="US_CPI_2026_08",
        indicator_key="US_CPI_YOY",
        reference_period=_REF,
        release_group_key="US_CPI_2026_08_GROUP",
    )
    core = EconomicEventOccurrence(
        occurrence_key="US_CPI_CORE_2026_08",
        indicator_key="US_CPI_CORE_YOY",
        reference_period=_REF,
        release_group_key="US_CPI_2026_08_GROUP",
    )
    assert headline.release_group_key == core.release_group_key
    assert headline.indicator_key != core.indicator_key
    assert headline.occurrence_key != core.occurrence_key


def test_rejects_blank_occurrence_key() -> None:
    with pytest.raises(ValueError, match="occurrence_key"):
        EconomicEventOccurrence(occurrence_key="", indicator_key="US_CPI_YOY")


def test_rejects_blank_indicator_key() -> None:
    with pytest.raises(ValueError, match="indicator_key"):
        EconomicEventOccurrence(occurrence_key="US_CPI_2026_08", indicator_key="")


def test_rejects_blank_release_group_key() -> None:
    with pytest.raises(ValueError, match="release_group_key"):
        EconomicEventOccurrence(
            occurrence_key="US_CPI_2026_08", indicator_key="US_CPI_YOY", release_group_key="  "
        )


def test_rejects_non_utctimestamp_reference_period() -> None:
    with pytest.raises(TypeError, match="reference_period"):
        EconomicEventOccurrence(
            occurrence_key="US_CPI_2026_08",
            indicator_key="US_CPI_YOY",
            reference_period=datetime(2026, 8, 1, tzinfo=UTC),  # type: ignore[arg-type]
        )
