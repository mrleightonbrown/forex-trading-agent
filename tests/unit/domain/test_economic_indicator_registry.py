"""FX-52A: unit tests for the canonical economic-indicator registry."""

from forex_agent.domain.economic_indicator_registry import (
    ECONOMIC_INDICATOR_DEFINITIONS,
    US_CPI_YOY,
    indicator_by_key,
)


def test_registry_has_no_duplicate_keys() -> None:
    keys = [d.key for d in ECONOMIC_INDICATOR_DEFINITIONS]
    assert len(keys) == len(set(keys))


def test_indicator_by_key_resolves_a_known_key() -> None:
    assert indicator_by_key("US_CPI_YOY") == US_CPI_YOY


def test_indicator_by_key_returns_none_for_unmapped_key() -> None:
    assert indicator_by_key("SOME_UNMAPPED_INDICATOR") is None


def test_registry_has_no_eur_entry() -> None:
    # ADR 0004's own honest finding: no official source cleared FX-52A's
    # admission bar for the euro area in this pass -- this must remain
    # visibly true rather than silently drift.
    assert not any(d.currency == "EUR" for d in ECONOMIC_INDICATOR_DEFINITIONS)


def test_every_definition_is_numeric_with_a_unit() -> None:
    # FX-52A never populates a numeric value for any of these regardless
    # -- but the registry's own claim about each indicator's TRUE nature
    # is independent of that story-scope restriction (see the module's
    # own docstring).
    for definition in ECONOMIC_INDICATOR_DEFINITIONS:
        assert definition.is_numeric is True
        assert definition.unit is not None and definition.unit.strip()
