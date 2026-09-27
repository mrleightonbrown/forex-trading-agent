"""FX-52A: unit tests for `build_release_group_key`. FX-52AH replaces
the old source-derived `build_occurrence_key` with `mint_occurrence_key`
(a genuinely provider-neutral internal identity) -- see the module's
own docstring for why."""

import re

import pytest

from forex_agent.domain.economic_calendar_occurrence_identity import (
    build_release_group_key,
    mint_occurrence_key,
)

_UUID4_SUFFIX_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.IGNORECASE
)


def test_mint_occurrence_key_is_prefixed_by_indicator_key() -> None:
    key = mint_occurrence_key("US_CPI_YOY")
    assert key.startswith("US_CPI_YOY:")


def test_mint_occurrence_key_suffix_is_a_uuid4() -> None:
    key = mint_occurrence_key("US_CPI_YOY")
    suffix = key.split(":", 1)[1]
    assert _UUID4_SUFFIX_PATTERN.match(suffix) is not None


def test_mint_occurrence_key_is_never_derived_from_any_source_identity() -> None:
    # No source/external_event_id parameter exists at all -- this test
    # documents that by construction, guarding against a future
    # signature change that would silently reintroduce FX-52A's own
    # original, corrected mistake (source-derived occurrence identity).
    import inspect

    signature = inspect.signature(mint_occurrence_key)
    assert list(signature.parameters) == ["indicator_key"]


def test_mint_occurrence_key_produces_a_different_key_each_call() -> None:
    first = mint_occurrence_key("US_CPI_YOY")
    second = mint_occurrence_key("US_CPI_YOY")
    assert first != second


def test_mint_occurrence_key_rejects_blank_indicator_key() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        mint_occurrence_key("")


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
