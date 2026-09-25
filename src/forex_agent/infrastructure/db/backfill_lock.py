"""SQLAlchemy/Postgres implementation of `BackfillLock` (FX-31H).

Uses a Postgres session-level advisory lock (`pg_advisory_lock`/
`pg_advisory_unlock`), held on ONE dedicated `AsyncConnection` obtained
directly from the engine (`engine.connect()`, not an ORM `Session`) for
the lock's entire held duration -- this is the fix `BackfillLock`'s own
docstring explains the need for: a Postgres advisory lock is tied to the
physical backend connection, not to any SQLAlchemy object, and an ORM
`Session`'s connection can change between commits.

`AUTOCOMMIT` isolation avoids holding an idle transaction open on this
connection for a potentially long backfill's whole duration (the lock
itself doesn't need one -- session-level advisory locks aren't
transaction-scoped either).

REQUIRED: construct this with a DEDICATED engine (see `infrastructure.
db.session.get_lock_engine`), never the same engine backing the
`candles`/`watermarks` sessions passed to the same `BackfillCandles`.
`pg_advisory_lock` BLOCKS while holding a checked-out connection --
under a small enough shared pool, two concurrent backfills for the same
series can deadlock: the waiting one's lock-connection occupies a pool
slot indefinitely, starving the holder's own worker session of the
connection it needs to finish (and thereby release the lock) — found
by external review, confirmed to be a genuine structural risk (not
just theoretical) before writing this warning.
"""

import hashlib
import struct
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument


def _advisory_lock_key(instrument: Instrument, granularity: Granularity) -> int:
    """A stable (not process-salted, unlike Python's own `hash()`) 64-bit
    signed key for Postgres' `pg_advisory_lock`/`pg_advisory_unlock`,
    derived from `(instrument, granularity)` -- the same pair
    `IngestionWatermarkRepository.set_watermark` keys a row on, though
    this key is otherwise unrelated to that repository."""
    digest = hashlib.sha256(f"{instrument.symbol}:{granularity.value}".encode()).digest()
    (key,) = struct.unpack(">q", digest[:8])
    return int(key)


class PostgresBackfillLock:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @asynccontextmanager
    async def acquire(
        self, instrument: Instrument, granularity: Granularity
    ) -> AsyncIterator[None]:
        key = _advisory_lock_key(instrument, granularity)
        async with self._engine.connect() as conn:
            conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
            await conn.execute(text("SELECT pg_advisory_lock(:key)"), {"key": key})
            try:
                yield
            finally:
                result = await conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                unlocked: bool = result.scalar_one()
                if not unlocked:
                    raise RuntimeError(
                        f"pg_advisory_unlock did not report releasing the lock for "
                        f"{instrument.symbol}/{granularity.value} (key={key}) -- it may be "
                        "held by a different connection than the one that acquired it, "
                        "which would mean this lock is no longer protecting anything"
                    )
