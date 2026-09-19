"""In-memory `MarketDataPort` test double (FX-26).

Seeded with a fixed `Candle` list; `get_candles` returns whatever falls
within `[start, end)`, mirroring the real contract. Supports raising on
specific requested ranges (`fail_on`) — the only way to test genuine
mid-backfill interruption/resume deterministically, without depending on
a real network failure.
"""

from collections.abc import Callable

from forex_agent.application.ports.exceptions import BrokerUnavailableError
from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.timestamps import UtcTimestamp


class FakeMarketDataPort:
    """Structurally satisfies `MarketDataPort` (a `Protocol`) — no
    inheritance needed; see
    `forex_agent.application.ports.market_data_port`."""

    def __init__(
        self,
        candles: list[Candle],
        fail_on: Callable[[UtcTimestamp, UtcTimestamp], bool] | None = None,
    ) -> None:
        self._candles = list(candles)
        self._fail_on = fail_on
        self.requests: list[tuple[UtcTimestamp, UtcTimestamp]] = []

    def set_fail_on(self, fail_on: Callable[[UtcTimestamp, UtcTimestamp], bool] | None) -> None:
        self._fail_on = fail_on

    async def get_candles(
        self,
        instrument: Instrument,
        granularity: Granularity,
        start: UtcTimestamp,
        end: UtcTimestamp,
    ) -> list[Candle]:
        self.requests.append((start, end))
        if self._fail_on is not None and self._fail_on(start, end):
            raise BrokerUnavailableError(f"simulated failure fetching [{start.value}, {end.value})")
        return [
            c
            for c in self._candles
            if c.instrument == instrument
            and c.granularity == granularity
            and start.value <= c.start_time.value < end.value
        ]
