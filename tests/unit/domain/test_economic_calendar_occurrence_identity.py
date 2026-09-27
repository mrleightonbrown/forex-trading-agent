"""FX-52A: unit tests for deterministic occurrence/release-group key
derivation."""

import pytest

from forex_agent.domain.economic_calendar_occurrence_identity import (
    build_occurrence_key,
    build_release_group_key,
)


def test_occurrence_key_is_deterministic() -> None:
    first = build_occurrence_key("BLS_ICS", "abc-123", "US_CPI_YOY")
    second = build_occurrence_key("BLS_ICS", "abc-123", "US_CPI_YOY")
    assert first == second


def test_occurrence_key_differs_by_source() -> None:
    a = build_occurrence_key("BLS_ICS", "abc-123", "US_CPI_YOY")
    b = build_occurrence_key("OTHER_SOURCE", "abc-123", "US_CPI_YOY")
    assert a != b


def test_occurrence_key_differs_by_indicator_for_a_release_package() -> None:
    payrolls = build_occurrence_key("BLS_ICS", "xyz", "US_NONFARM_PAYROLLS")
    unemployment = build_occurrence_key("BLS_ICS", "xyz", "US_UNEMPLOYMENT_RATE")
    assert payrolls != unemployment


def test_occurrence_key_survives_a_reschedule_conceptually() -> None:
    # A reschedule never changes source/external_event_id/indicator_key
    # -- the same three inputs must always yield the same key,
    # regardless of what the schedule itself later says.
    external_id = "247309@bank-banque-canada.ca"
    before = build_occurrence_key("BOC_ICS", external_id, "CAD_POLICY_RATE_DECISION")
    after = build_occurrence_key("BOC_ICS", external_id, "CAD_POLICY_RATE_DECISION")
    assert before == after


@pytest.mark.parametrize(
    "source,external_event_id,indicator_key",
    [("", "x", "Y"), ("S", "", "Y"), ("S", "x", "")],
)
def test_occurrence_key_rejects_blank_components(
    source: str, external_event_id: str, indicator_key: str
) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        build_occurrence_key(source, external_event_id, indicator_key)


def test_release_group_key_shared_across_package_members() -> None:
    group_for_payrolls_context = build_release_group_key("BLS_ICS", "xyz")
    group_for_unemployment_context = build_release_group_key("BLS_ICS", "xyz")
    assert group_for_payrolls_context == group_for_unemployment_context


def test_release_group_key_independent_of_indicator_key() -> None:
    # build_release_group_key never takes an indicator_key at all --
    # this test documents that by construction (no such argument
    # exists), guarding against a future signature change that would
    # silently break the "one group per source item" guarantee.
    import inspect

    signature = inspect.signature(build_release_group_key)
    assert "indicator_key" not in signature.parameters


@pytest.mark.parametrize("source,external_event_id", [("", "x"), ("S", "")])
def test_release_group_key_rejects_blank_components(source: str, external_event_id: str) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        build_release_group_key(source, external_event_id)
