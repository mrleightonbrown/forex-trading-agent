"""In-memory `BrokerPort` test double.

Lets anything depending on `BrokerPort` be tested before FX-4's real OANDA
adapter exists — and afterwards, for fast unit tests that shouldn't need a
live broker connection.
"""

from decimal import Decimal

from forex_agent.application.ports.exceptions import InstrumentNotAvailableError
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.money import Money
from forex_agent.domain.price import Price

_DEFAULT_BALANCE = Money(Decimal("0"), "USD")


class FakeBrokerPort:
    """Structurally satisfies `BrokerPort` (a `Protocol`) — no inheritance
    needed; see `forex_agent.application.ports.broker_port`."""

    def __init__(
        self,
        prices: dict[Instrument, Price] | None = None,
        balance: Money = _DEFAULT_BALANCE,
    ) -> None:
        self._prices = dict(prices or {})
        self._balance = balance

    def set_price(self, instrument: Instrument, price: Price) -> None:
        self._prices[instrument] = price

    def set_balance(self, balance: Money) -> None:
        self._balance = balance

    async def get_price(self, instrument: Instrument) -> Price:
        try:
            return self._prices[instrument]
        except KeyError:
            raise InstrumentNotAvailableError(instrument) from None

    async def get_account_balance(self) -> Money:
        return self._balance
