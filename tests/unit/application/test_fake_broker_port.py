from decimal import Decimal

import pytest

from forex_agent.application.ports.broker_port import BrokerPort
from forex_agent.application.ports.exceptions import InstrumentNotAvailableError
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.money import Money
from forex_agent.domain.price import Price
from tests.fakes.broker_port import FakeBrokerPort

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")


def test_fake_satisfies_broker_port_protocol() -> None:
    # Assignment alone is the check: mypy verifies FakeBrokerPort matches
    # the BrokerPort Protocol shape structurally, with no inheritance.
    fake: BrokerPort = FakeBrokerPort()
    assert fake is not None


@pytest.mark.asyncio
async def test_get_price_returns_configured_price() -> None:
    price = Price(bid=Decimal("1.1000"), ask=Decimal("1.1002"))
    fake = FakeBrokerPort(prices={EUR_USD: price})

    assert await fake.get_price(EUR_USD) == price


@pytest.mark.asyncio
async def test_get_price_raises_for_unconfigured_instrument() -> None:
    fake = FakeBrokerPort()

    with pytest.raises(InstrumentNotAvailableError):
        await fake.get_price(EUR_USD)


@pytest.mark.asyncio
async def test_get_account_balance_defaults_to_zero_usd() -> None:
    fake = FakeBrokerPort()

    assert await fake.get_account_balance() == Money(Decimal("0"), "USD")


@pytest.mark.asyncio
async def test_set_balance_updates_returned_balance() -> None:
    fake = FakeBrokerPort()
    fake.set_balance(Money(Decimal("500"), "USD"))

    assert await fake.get_account_balance() == Money(Decimal("500"), "USD")


@pytest.mark.asyncio
async def test_set_price_updates_returned_price() -> None:
    fake = FakeBrokerPort()
    price = Price(bid=Decimal("1.3000"), ask=Decimal("1.3003"))
    fake.set_price(EUR_USD, price)

    assert await fake.get_price(EUR_USD) == price
