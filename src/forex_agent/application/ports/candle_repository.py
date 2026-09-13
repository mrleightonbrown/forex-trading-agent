from typing import Protocol

from forex_agent.domain.candle import Candle


class CandleRepository(Protocol):
    """Storage for historical candles.

    A `Protocol`, matching `BrokerPort`'s style (FX-3) — the concrete
    SQLAlchemy implementation just needs to match this shape.
    """

    async def upsert_many(self, candles: list[Candle]) -> int:
        """Insert or update each candle, keyed on
        (instrument, granularity, start_time). Calling this repeatedly with
        the same candles must not create duplicate rows — CLAUDE.md requires
        regression coverage against "duplicate events"/"provider
        duplication". Returns the number of candles written.
        """
        ...
