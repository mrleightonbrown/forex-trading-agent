"""FX-52A: unit tests for the canonical economic-indicator registry.
FX-54 adds `indicators_by_currency` coverage."""

from forex_agent.domain.economic_indicator_registry import (
    CAD_POLICY_RATE_DECISION,
    ECONOMIC_INDICATOR_DEFINITIONS,
    GBP_GDP_QOQ,
    US_CPI_YOY,
    US_NONFARM_PAYROLLS,
    US_UNEMPLOYMENT_RATE,
    indicator_by_key,
    indicators_by_currency,
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


def test_indicators_by_currency_resolves_usd() -> None:
    # Order matches ECONOMIC_INDICATOR_DEFINITIONS' own declaration order.
    assert indicators_by_currency("USD") == (
        US_CPI_YOY,
        US_NONFARM_PAYROLLS,
        US_UNEMPLOYMENT_RATE,
    )


def test_indicators_by_currency_resolves_a_single_indicator() -> None:
    assert indicators_by_currency("GBP") == (GBP_GDP_QOQ,)
    assert indicators_by_currency("CAD") == (CAD_POLICY_RATE_DECISION,)


def test_indicators_by_currency_returns_empty_tuple_for_eur() -> None:
    # FX-54 Section 23: EUR has zero adopted source coverage -- this
    # must be an honest empty tuple, never an error and never a
    # fabricated entry.
    assert indicators_by_currency("EUR") == ()


def test_indicators_by_currency_returns_empty_tuple_for_unrecognized_currency() -> None:
    assert indicators_by_currency("XYZ") == ()
