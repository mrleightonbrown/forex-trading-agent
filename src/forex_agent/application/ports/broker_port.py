from typing import Protocol

from forex_agent.domain.instrument import Instrument
from forex_agent.domain.money import Money
from forex_agent.domain.price import Price


class BrokerPort(Protocol):
    """The connectivity contract a broker adapter must satisfy.

    Deliberately read-only for now. CLAUDE.md's execution pipeline (trade
    hypothesis -> risk decision -> approved execution intent -> order) has
    no risk/execution-intent layer built yet, so no order-placement method
    belongs here — add one only once Risk Engine / Paper Trading Execution
    work is actually assigned. Until then this port exists to support price
    quotes and account state, e.g. for market data ingestion.

    A `Protocol`, not an ABC: FX-4's real OANDA adapter and any test double
    (see `tests.fakes.broker_port.FakeBrokerPort`) only need to match this
    shape, not inherit from it.
    """

    async def get_price(self, instrument: Instrument) -> Price:
        """Current bid/ask quote for `instrument`.

        Raises `forex_agent.application.ports.exceptions.BrokerPortError`
        (or a subclass) on failure — never a provider-specific exception.
        """
        ...

    async def get_account_balance(self) -> Money:
        """Current account balance.

        Raises `forex_agent.application.ports.exceptions.BrokerPortError`
        (or a subclass) on failure — never a provider-specific exception.
        """
        ...
