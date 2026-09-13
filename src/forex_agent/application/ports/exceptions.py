"""Exception hierarchy for `BrokerPort` and `MarketDataPort` failures.

Concrete adapters (e.g. FX-4/FX-6's OANDA adapters) must catch their
provider-specific exceptions and re-raise one of these, so application code
never has to know about — or import — a provider's exception types.

Shared by both ports rather than each having its own near-identical
hierarchy — same failure shapes (unavailable / instrument not found).
Worth a rename to something more provider-agnostic than "Broker" if a
third, differently-shaped port ever needs its own failure modes.
"""

from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.timestamps import UtcTimestamp


class BrokerPortError(Exception):
    """Base class for all BrokerPort/MarketDataPort failures."""


class InstrumentNotAvailableError(BrokerPortError):
    """Raised when a broker has no quote/data available for an instrument."""

    def __init__(self, instrument: Instrument) -> None:
        self.instrument = instrument
        super().__init__(f"no data available for instrument {instrument.symbol}")


class BrokerUnavailableError(BrokerPortError):
    """Raised when the broker connection itself fails (network, auth, an
    outage, ...) rather than a specific instrument being unavailable."""


class CandleRangeTooLargeError(BrokerPortError):
    """Raised when a requested candle range exceeds what a single request
    can return. Pagination for larger backfills is not implemented yet —
    see `forex_agent.application.ports.market_data_port.MarketDataPort`."""

    def __init__(
        self,
        instrument: Instrument,
        granularity: Granularity,
        start: UtcTimestamp,
        end: UtcTimestamp,
    ) -> None:
        self.instrument = instrument
        self.granularity = granularity
        self.start = start
        self.end = end
        super().__init__(
            f"requested candle range for {instrument.symbol} at {granularity.value} "
            f"from {start.value.isoformat()} to {end.value.isoformat()} exceeds what a "
            "single request can return; pagination is not implemented yet"
        )
