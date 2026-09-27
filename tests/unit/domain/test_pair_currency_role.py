"""FX-54: unit tests for `PairCurrencyRole`/`pair_role_by_indicator_key`
-- pair relevance resolved exclusively through `EconomicIndicatorDefinition.
currency`, never inferred from an indicator's name/source/occurrence key."""

from forex_agent.domain.instrument import Instrument
from forex_agent.domain.pair_currency_role import PairCurrencyRole, pair_role_by_indicator_key


def test_gbp_usd_gbp_gdp_is_base_and_usd_indicators_are_quote() -> None:
    instrument = Instrument(base_currency="GBP", quote_currency="USD")
    roles = pair_role_by_indicator_key(instrument)

    assert roles["GBP_GDP_QOQ"] is PairCurrencyRole.BASE
    assert roles["US_CPI_YOY"] is PairCurrencyRole.QUOTE
    assert roles["US_NONFARM_PAYROLLS"] is PairCurrencyRole.QUOTE
    assert roles["US_UNEMPLOYMENT_RATE"] is PairCurrencyRole.QUOTE
    # CAD is neither side of this pair -- not pair-relevant at all.
    assert "CAD_POLICY_RATE_DECISION" not in roles


def test_usd_cad_cad_policy_is_quote_and_gbp_is_excluded() -> None:
    instrument = Instrument(base_currency="USD", quote_currency="CAD")
    roles = pair_role_by_indicator_key(instrument)

    assert roles["US_CPI_YOY"] is PairCurrencyRole.BASE
    assert roles["CAD_POLICY_RATE_DECISION"] is PairCurrencyRole.QUOTE
    assert "GBP_GDP_QOQ" not in roles


def test_eur_usd_eur_has_zero_tracked_indicators() -> None:
    # FX-54 Section 23: EUR currently has no adopted official timing
    # source at all -- the role map must simply have no EUR-currency
    # entries, never an error, never a fabricated indicator.
    instrument = Instrument(base_currency="EUR", quote_currency="USD")
    roles = pair_role_by_indicator_key(instrument)

    assert roles["US_CPI_YOY"] is PairCurrencyRole.QUOTE
    assert not any(role is PairCurrencyRole.BASE for role in roles.values())


def test_reversed_pair_swaps_base_and_quote_roles() -> None:
    gbp_usd = pair_role_by_indicator_key(Instrument(base_currency="GBP", quote_currency="USD"))
    usd_gbp = pair_role_by_indicator_key(Instrument(base_currency="USD", quote_currency="GBP"))

    assert gbp_usd["GBP_GDP_QOQ"] is PairCurrencyRole.BASE
    assert usd_gbp["GBP_GDP_QOQ"] is PairCurrencyRole.QUOTE
    assert gbp_usd["US_CPI_YOY"] is PairCurrencyRole.QUOTE
    assert usd_gbp["US_CPI_YOY"] is PairCurrencyRole.BASE
