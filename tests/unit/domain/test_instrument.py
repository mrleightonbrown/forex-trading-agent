import pytest

from forex_agent.domain.instrument import Instrument, parse_instrument


def test_valid_instrument_has_symbol() -> None:
    instrument = Instrument(base_currency="EUR", quote_currency="USD")

    assert instrument.symbol == "EUR_USD"
    assert instrument.pip_decimal_places == 4


def test_custom_pip_decimal_places() -> None:
    instrument = Instrument(base_currency="USD", quote_currency="JPY", pip_decimal_places=2)

    assert instrument.pip_decimal_places == 2


def test_rejects_same_base_and_quote_currency() -> None:
    with pytest.raises(ValueError, match="must differ"):
        Instrument(base_currency="EUR", quote_currency="EUR")


@pytest.mark.parametrize("code", ["eur", "EU", "EURO", "123"])
def test_rejects_invalid_currency_code(code: str) -> None:
    with pytest.raises(ValueError, match="currency code"):
        Instrument(base_currency=code, quote_currency="USD")


def test_rejects_non_positive_pip_decimal_places() -> None:
    with pytest.raises(ValueError, match="pip_decimal_places"):
        Instrument(base_currency="EUR", quote_currency="USD", pip_decimal_places=0)


def test_instrument_is_immutable_and_hashable() -> None:
    instrument = Instrument(base_currency="EUR", quote_currency="USD")

    with pytest.raises(AttributeError):
        instrument.base_currency = "GBP"  # type: ignore[misc]

    assert hash(instrument) == hash(Instrument(base_currency="EUR", quote_currency="USD"))


# --- FX-60 Section 4: parse_instrument ---------------------------------------


@pytest.mark.parametrize(
    "pair_code,base,quote",
    [
        ("EUR/USD", "EUR", "USD"),
        ("USD/CAD", "USD", "CAD"),
        ("GBP/USD", "GBP", "USD"),
    ],
)
def test_parse_instrument_resolves_base_and_quote(pair_code: str, base: str, quote: str) -> None:
    instrument = parse_instrument(pair_code)

    assert instrument.base_currency == base
    assert instrument.quote_currency == quote


def test_parse_instrument_is_not_hard_coded_to_three_pairs() -> None:
    # Section 4: "Do not hard-code only EUR/USD, GBP/USD, USD/CAD."
    instrument = parse_instrument("AUD/NZD")

    assert instrument.base_currency == "AUD"
    assert instrument.quote_currency == "NZD"


@pytest.mark.parametrize(
    "malformed",
    ["EURUSD", "EUR-USD", "EUR/USD/CAD", "EUR/", "/USD", "", "EUR//USD"],
)
def test_parse_instrument_rejects_malformed_symbols(malformed: str) -> None:
    with pytest.raises(ValueError, match="BASE/QUOTE"):
        parse_instrument(malformed)


def test_parse_instrument_rejects_same_currency_pair() -> None:
    with pytest.raises(ValueError, match="must differ"):
        parse_instrument("EUR/EUR")


def test_parse_instrument_rejects_unresolvable_currency_code() -> None:
    with pytest.raises(ValueError, match="currency code"):
        parse_instrument("EURO/USD")


def test_parse_instrument_custom_pip_decimal_places() -> None:
    instrument = parse_instrument("USD/JPY", pip_decimal_places=2)

    assert instrument.pip_decimal_places == 2
