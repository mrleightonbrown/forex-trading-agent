from typing import Protocol

from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.timestamps import UtcTimestamp


class MarketDataPort(Protocol):
    """Historical candle data.

    Separate from `BrokerPort` (FX-3) deliberately — live quote/balance
    connectivity and historical/bulk candle fetching are different shapes
    of concern (ranged, potentially backfill-heavy), even though FX-6's
    concrete adapter happens to be OANDA for both.
    """

    async def get_candles(
        self,
        instrument: Instrument,
        granularity: Granularity,
        start: UtcTimestamp,
        end: UtcTimestamp,
    ) -> list[Candle]:
        """Candles for `instrument` at `granularity` within [start, end).

        Bounded to what a single request can return — raises
        `forex_agent.application.ports.exceptions.CandleRangeTooLargeError`
        rather than silently truncating if the range is too large.
        Pagination for larger backfills is not implemented yet.

        Raises `forex_agent.application.ports.exceptions.BrokerPortError`
        (or a subclass) on any other failure — never a provider-specific
        exception.
        """
        ...
