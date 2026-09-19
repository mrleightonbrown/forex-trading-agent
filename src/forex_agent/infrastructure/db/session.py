"""Async SQLAlchemy engine/session factory.

Composition-root code (`apps`) constructs sessions via `get_session`; nothing
in `application` or `domain` should import `sqlalchemy` directly.
"""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from forex_agent.apps.settings import get_settings


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(settings.database_url, pool_pre_ping=True)


@lru_cache(maxsize=1)
def get_lock_engine() -> AsyncEngine:
    """A SEPARATE engine (own connection pool), dedicated to
    `PostgresBackfillLock` (FX-31H).

    Never share `get_engine()`'s own pool with the lock: `Postgres
    BackfillLock.acquire()` blocks on `pg_advisory_lock`, holding a
    checked-out connection for as long as it waits -- if that connection
    comes from the SAME pool a waiting `BackfillCandles` call's own
    `candles`/`watermarks` session also draws from, a small enough pool
    can deadlock. Concretely, with `pool_size=2` and two concurrent
    backfills for the same series: A checks out connection 1 and holds
    the lock; B checks out connection 2 and blocks waiting for it. A now
    needs a connection for its OWN `get_watermark`/`upsert_many` work to
    finish (and release the lock) -- none left, since B is holding the
    pool's only other slot while waiting. A can't finish to release the
    lock; B can't release its connection until the lock (held by A) is
    released. Neither side can proceed. A dedicated engine for the lock
    makes this structurally impossible: lock connections and worker
    connections can never compete for the same pool slots."""
    settings = get_settings()
    return create_async_engine(settings.database_url, pool_pre_ping=True)


@lru_cache(maxsize=1)
def _session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped session."""
    async with _session_factory()() as session:
        yield session
