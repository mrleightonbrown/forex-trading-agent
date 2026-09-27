"""FX-54V: unit tests for `apps.api.pairs` -- the dashboard's own
supported-pair registry."""

from forex_agent.apps.api.pairs import SUPPORTED_PAIRS, resolve_pair
from forex_agent.domain.instrument import Instrument


def test_supported_pairs_has_exactly_the_three_fx_54v_pairs() -> None:
    assert set(SUPPORTED_PAIRS) == {"EUR_USD", "GBP_USD", "USD_CAD"}


def test_resolve_pair_returns_the_matching_instrument() -> None:
    assert resolve_pair("GBP_USD") == Instrument(base_currency="GBP", quote_currency="USD")
    assert resolve_pair("USD_CAD") == Instrument(base_currency="USD", quote_currency="CAD")


def test_resolve_pair_returns_none_for_unsupported_pair() -> None:
    assert resolve_pair("AUD_USD") is None
    assert resolve_pair("") is None
