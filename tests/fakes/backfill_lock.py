"""In-memory `BackfillLock` test double (FX-31H).

Uses one real `asyncio.Lock` per `(instrument, granularity)` key --
genuinely serializes concurrent callers in tests too, the same guarantee
the real `PostgresBackfillLock` gives, not just a no-op stand-in."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument


class FakeBackfillLock:
    """Structurally satisfies `BackfillLock` (a `Protocol`) — no
    inheritance needed; see
    `forex_agent.application.ports.backfill_lock`."""

    def __init__(self) -> None:
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    @asynccontextmanager
    async def acquire(
        self, instrument: Instrument, granularity: Granularity
    ) -> AsyncIterator[None]:
        key = (instrument.symbol, granularity.value)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            yield
