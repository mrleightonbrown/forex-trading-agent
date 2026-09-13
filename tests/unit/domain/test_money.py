from decimal import Decimal

import pytest

from forex_agent.domain.money import Money


def test_valid_money() -> None:
    money = Money(amount=Decimal("100.50"), currency="USD")

    assert money.amount == Decimal("100.50")
    assert money.currency == "USD"


def test_rejects_float_amount() -> None:
    with pytest.raises(TypeError, match="Decimal"):
        Money(amount=100.50, currency="USD")  # type: ignore[arg-type]


@pytest.mark.parametrize("currency", ["usd", "US", "DOLLAR", "123"])
def test_rejects_invalid_currency_code(currency: str) -> None:
    with pytest.raises(ValueError, match="currency code"):
        Money(amount=Decimal("100"), currency=currency)


def test_add_same_currency() -> None:
    total = Money(Decimal("100"), "USD") + Money(Decimal("50"), "USD")

    assert total == Money(Decimal("150"), "USD")


def test_subtract_same_currency() -> None:
    result = Money(Decimal("100"), "USD") - Money(Decimal("30"), "USD")

    assert result == Money(Decimal("70"), "USD")


def test_add_different_currency_rejected() -> None:
    with pytest.raises(ValueError, match="currenc"):
        Money(Decimal("100"), "USD") + Money(Decimal("50"), "EUR")


def test_subtract_different_currency_rejected() -> None:
    with pytest.raises(ValueError, match="currenc"):
        Money(Decimal("100"), "USD") - Money(Decimal("50"), "EUR")
