"""Exception hierarchy for `BrokerPort` failures.

Concrete adapters (e.g. FX-4's OANDA adapter) must catch their
provider-specific exceptions and re-raise one of these, so application code
never has to know about — or import — a provider's exception types.
"""

from forex_agent.domain.instrument import Instrument


class BrokerPortError(Exception):
    """Base class for all BrokerPort failures."""


class InstrumentNotAvailableError(BrokerPortError):
    """Raised when a broker has no quote/data available for an instrument."""

    def __init__(self, instrument: Instrument) -> None:
        self.instrument = instrument
        super().__init__(f"no data available for instrument {instrument.symbol}")


class BrokerUnavailableError(BrokerPortError):
    """Raised when the broker connection itself fails (network, auth, an
    outage, ...) rather than a specific instrument being unavailable."""
