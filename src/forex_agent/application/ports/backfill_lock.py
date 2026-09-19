"""FX-31 (connection-pinning correction FX-31H): serializes concurrent
`BackfillCandles` calls for the same `(instrument, granularity)`.

Deliberately its OWN port, separate from `IngestionWatermarkRepository`
-- FX-31's first attempt put `acquire_lock`/`release_lock` on the
watermark repository and implemented them via a Postgres session-level
advisory lock issued through the SAME `AsyncSession` `BackfillCandles`
uses for its `candles`/`watermarks` work. That's broken: `Session.
commit()` checks its underlying DBAPI connection back in to the pool
(confirmed directly, not assumed -- see docs/DECISIONS.md), and
`BackfillCandles` commits once per page via `upsert_many`/
`set_watermark`. A Postgres advisory lock belongs to the physical
backend connection/session, not to any SQLAlchemy object -- if a later
page's work happens to check out a DIFFERENT physical connection than
the one the lock was acquired on (which the pool does not guarantee
against), the lock silently stops protecting anything, and
`pg_advisory_unlock` on the wrong connection returns `false` (a
stranded lock) rather than raising.

The fix is a lock that owns and pins its OWN dedicated physical
connection for its entire held duration, independent of whatever
connection churn the watermark/candle repositories' own session goes
through. Separating this out as its own abstraction (rather than
folding physical-connection lifetime into the watermark repository,
which already has its own job -- persisting state) keeps that
distinction explicit at the port level, not just in a comment.

Implementations that block while acquiring (the real one does, on
`pg_advisory_lock`) MUST use a connection pool entirely separate from
whatever pool backs the `candles`/`watermarks` sessions passed to the
same `BackfillCandles` -- see `PostgresBackfillLock`'s own docstring
for the deadlock a shared pool can cause under real contention (found
by external review, confirmed as a genuine structural risk before
documenting it here).
"""

from contextlib import AbstractAsyncContextManager
from typing import Protocol

from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument


class BackfillLock(Protocol):
    def acquire(
        self, instrument: Instrument, granularity: Granularity
    ) -> AbstractAsyncContextManager[None]:
        """An async context manager: blocks on entry until this series'
        lock is exclusively held (on one pinned connection, in the real
        implementation), releases it on exit -- including on an
        exception, so a failed backfill never leaves the lock stuck.
        """
        ...
