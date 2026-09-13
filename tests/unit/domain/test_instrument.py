import pytest

from forex_agent.domain.instrument import Instrument


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
