"""In-memory `IngestionWatermarkRepository` test double (FX-26,
`acquire_lock`/`release_lock` FX-31)."""

import asyncio

from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.timestamps import UtcTimestamp


class FakeIngestionWatermarkRepository:
    """Structurally satisfies `IngestionWatermarkRepository` (a
    `Protocol`) — no inheritance needed; see
    `forex_agent.application.ports.ingestion_watermark_repository`.

    `acquire_lock`/`release_lock` use one real `asyncio.Lock` per
    `(instrument, granularity)` key -- genuinely serializes concurrent
    callers in tests too, the same guarantee the real Postgres advisory
    lock gives, not just a no-op stand-in."""

    def __init__(self) -> None:
        self._watermarks: dict[tuple[str, str], tuple[UtcTimestamp, UtcTimestamp]] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    async def get_watermark(
        self, instrument: Instrument, granularity: Granularity
    ) -> tuple[UtcTimestamp, UtcTimestamp] | None:
        return self._watermarks.get((instrument.symbol, granularity.value))

    async def set_watermark(
        self,
        instrument: Instrument,
        granularity: Granularity,
        earliest: UtcTimestamp,
        latest: UtcTimestamp,
    ) -> None:
        self._watermarks[(instrument.symbol, granularity.value)] = (earliest, latest)

    async def acquire_lock(self, instrument: Instrument, granularity: Granularity) -> None:
        key = (instrument.symbol, granularity.value)
        lock = self._locks.setdefault(key, asyncio.Lock())
        await lock.acquire()

    async def release_lock(self, instrument: Instrument, granularity: Granularity) -> None:
        key = (instrument.symbol, granularity.value)
        lock = self._locks.get(key)
        if lock is not None and lock.locked():
            lock.release()
