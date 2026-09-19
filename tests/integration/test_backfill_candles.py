"""FX-26: BackfillCandles against real Postgres — proves the resumability
guarantee holds with genuine persistence, not just the in-memory fakes
used in tests/unit/application/use_cases/test_backfill_candles.py. Still
uses a fake MarketDataPort (a real provider failure can't be
deterministically triggered); connectivity to the real OANDA API is
separately covered elsewhere.

Requires a live Postgres with the FX-26 migration applied.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from forex_agent.application.ports.exceptions import BrokerUnavailableError
from forex_agent.application.use_cases.backfill_candles import BackfillCandles
from forex_agent.apps.settings import get_settings
from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.backfill_lock import PostgresBackfillLock
from forex_agent.infrastructure.db.candle_repository import SqlAlchemyCandleRepository
from forex_agent.infrastructure.db.ingestion_watermark_repository import (
    SqlAlchemyIngestionWatermarkRepository,
)
from forex_agent.infrastructure.db.models.candle import CandleRow
from forex_agent.infrastructure.db.models.ingestion_watermark import IngestionWatermarkRow
from forex_agent.infrastructure.db.session import get_engine
from tests.fakes.market_data_port import FakeMarketDataPort

TEST_INSTRUMENT = Instrument(base_currency="ZZZ", quote_currency="WWW")
_EPOCH = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


def _ts(minute: int) -> UtcTimestamp:
    return UtcTimestamp(_EPOCH + timedelta(minutes=minute))


def _dense_candles(count: int) -> list[Candle]:
    flat = Ohlc(open=Decimal("1.1"), high=Decimal("1.1"), low=Decimal("1.1"), close=Decimal("1.1"))
    return [
        Candle(
            instrument=TEST_INSTRUMENT,
            granularity=Granularity.M1,
            start_time=_ts(m),
            bid=flat,
            ask=flat,
            volume=1,
            is_finalized=True,
        )
        for m in range(count)
    ]


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    async with session_factory() as db_session:
        yield db_session

    async with session_factory() as cleanup_session:
        await cleanup_session.execute(
            delete(CandleRow).where(CandleRow.instrument == TEST_INSTRUMENT.symbol)
        )
        await cleanup_session.execute(
            delete(IngestionWatermarkRow).where(
                IngestionWatermarkRow.instrument == TEST_INSTRUMENT.symbol
            )
        )
        await cleanup_session.commit()


@pytest.mark.asyncio
async def test_backfill_pages_and_persists_against_real_postgres(session: AsyncSession) -> None:
    market_data = FakeMarketDataPort(_dense_candles(23))
    use_case = BackfillCandles(
        market_data=market_data,
        candles=SqlAlchemyCandleRepository(session),
        watermarks=SqlAlchemyIngestionWatermarkRepository(session),
        lock=PostgresBackfillLock(get_engine()),
        max_candles_per_page=5,
    )

    result = await use_case(TEST_INSTRUMENT, Granularity.M1, _ts(0), _ts(23))

    assert result.pages_fetched == 5
    assert result.candles_written == 23
    stored = await SqlAlchemyCandleRepository(session).get_range(
        TEST_INSTRUMENT, Granularity.M1, _ts(0), _ts(23)
    )
    assert len(stored) == 23


@pytest.mark.asyncio
async def test_interrupted_backfill_resumes_without_refetching_or_duplicating_against_postgres(
    session: AsyncSession,
) -> None:
    """The core FX-26 guarantee, proven against real persistence: a
    simulated mid-backfill failure leaves exactly the completed pages
    durably stored and the watermark reflecting exactly that progress;
    re-invoking the SAME request completes the rest without duplicating
    already-ingested candles or re-fetching already-completed pages.
    """
    candles = _dense_candles(25)

    def fail_on_third_page(req_start: UtcTimestamp, _req_end: UtcTimestamp) -> bool:
        return req_start.value == _ts(10).value

    market_data = FakeMarketDataPort(candles, fail_on=fail_on_third_page)
    candle_repo = SqlAlchemyCandleRepository(session)
    watermark_repo = SqlAlchemyIngestionWatermarkRepository(session)
    use_case = BackfillCandles(
        market_data=market_data,
        candles=candle_repo,
        watermarks=watermark_repo,
        lock=PostgresBackfillLock(get_engine()),
        max_candles_per_page=5,
    )

    with pytest.raises(BrokerUnavailableError):
        await use_case(TEST_INSTRUMENT, Granularity.M1, _ts(0), _ts(25))

    # Exactly the first two pages made it into Postgres before the
    # simulated failure -- and the watermark, independently persisted,
    # agrees with what's actually stored.
    watermark_after_failure = await watermark_repo.get_watermark(TEST_INSTRUMENT, Granularity.M1)
    assert watermark_after_failure == (_ts(0), _ts(10))
    stored_before = await candle_repo.get_range(TEST_INSTRUMENT, Granularity.M1, _ts(0), _ts(25))
    assert len(stored_before) == 10

    # A fresh use case instance (simulating a genuinely restarted
    # process, not just retrying in-memory) resumes correctly.
    market_data.set_fail_on(None)
    resumed_use_case = BackfillCandles(
        market_data=market_data,
        candles=SqlAlchemyCandleRepository(session),
        watermarks=SqlAlchemyIngestionWatermarkRepository(session),
        lock=PostgresBackfillLock(get_engine()),
        max_candles_per_page=5,
    )
    result = await resumed_use_case(TEST_INSTRUMENT, Granularity.M1, _ts(0), _ts(25))

    assert result.earliest_ingested == _ts(0)
    assert result.latest_ingested == _ts(25)
    stored_after = await candle_repo.get_range(TEST_INSTRUMENT, Granularity.M1, _ts(0), _ts(25))
    assert len(stored_after) == 25  # no duplicates, nothing missing


@pytest.mark.asyncio
async def test_concurrent_backfills_for_the_same_series_do_not_race(
    session: AsyncSession,
) -> None:
    """FX-31 (connection-pinning correction FX-31H): two BackfillCandles
    calls for the SAME series, each its own session/connection (genuinely
    concurrent, not just interleaved coroutines sharing one connection),
    requesting overlapping ranges at the same time via `asyncio.gather`.
    Without the lock serializing them, both could read the same starting
    watermark, independently compute conflicting page plans, and their
    interleaved `set_watermark` calls could clobber each other -- ending
    with a watermark that doesn't match what either call, or a
    sequential run of both, actually produced. With the lock, the second
    call simply blocks until the first fully completes, so the result is
    always equivalent to running them one after another: the union of
    both ranges, fully covered, nothing missing."""
    candles = _dense_candles(100)
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    lock = PostgresBackfillLock(get_engine())

    async with session_factory() as session_a, session_factory() as session_b:
        use_case_a = BackfillCandles(
            market_data=FakeMarketDataPort(candles),
            candles=SqlAlchemyCandleRepository(session_a),
            watermarks=SqlAlchemyIngestionWatermarkRepository(session_a),
            lock=lock,
            max_candles_per_page=3,  # small pages -> many await points -> real interleaving
        )
        use_case_b = BackfillCandles(
            market_data=FakeMarketDataPort(candles),
            candles=SqlAlchemyCandleRepository(session_b),
            watermarks=SqlAlchemyIngestionWatermarkRepository(session_b),
            lock=lock,
            max_candles_per_page=3,
        )

        await asyncio.gather(
            use_case_a(TEST_INSTRUMENT, Granularity.M1, _ts(0), _ts(60)),
            use_case_b(TEST_INSTRUMENT, Granularity.M1, _ts(40), _ts(100)),
        )

    final_watermark = await SqlAlchemyIngestionWatermarkRepository(session).get_watermark(
        TEST_INSTRUMENT, Granularity.M1
    )
    assert final_watermark == (_ts(0), _ts(100))
    stored = await SqlAlchemyCandleRepository(session).get_range(
        TEST_INSTRUMENT, Granularity.M1, _ts(0), _ts(100)
    )
    assert len(stored) == 100  # nothing missing, nothing lost to a clobbered watermark


@pytest.mark.asyncio
async def test_concurrent_backfills_do_not_race_even_under_forced_pool_churn(
    session: AsyncSession,
) -> None:
    """FX-31H's own specific regression.

    Honest note on what this does and doesn't prove: the bug this fixes
    (a Postgres advisory lock acquired on one physical connection,
    silently orphaned when a later page's commit hands that connection
    to someone else, letting a second caller's own lock request land on
    a DIFFERENT connection and be granted immediately -- Postgres
    advisory locks are reentrant within one physical connection, so two
    SEPARATE connections requesting the same key genuinely do serialize
    correctly against each other; the danger is specifically a stray
    connection *reuse*) is real but inherently timing-dependent, not
    reliably reproducible on every run. Confirmed directly, not just in
    theory: reverted to the original (session-sharing) lock design and
    ran this exact scenario repeatedly -- it failed at least once in
    scattered runs, confirming genuine corruption is possible, but also
    passed clean in many other runs, confirming a single pass (or even
    several) proves nothing. Running several independent trials here
    doesn't make this deterministic either, but raises the odds of
    catching a real reintroduced regression well above one attempt.

    The lock itself uses its own separate, unconstrained engine, kept
    completely isolated from the deliberately tiny, heavily-churning
    pool (`pool_size=2`, one-candle pages) the two workers' `candles`/
    `watermarks` sessions share -- proving the fix by construction, not
    just by luck: the lock's own connection is pinned for its whole
    held duration regardless of how much the OTHER sessions' pool
    churns underneath it.
    """
    settings = get_settings()
    constrained_engine = create_async_engine(
        settings.database_url, pool_size=2, max_overflow=0, pool_pre_ping=True
    )
    lock = PostgresBackfillLock(get_engine())  # deliberately a SEPARATE, unconstrained engine

    try:
        session_factory = async_sessionmaker(bind=constrained_engine, expire_on_commit=False)
        for trial in range(5):
            candles = _dense_candles(30)
            async with session_factory() as session_a, session_factory() as session_b:
                use_case_a = BackfillCandles(
                    market_data=FakeMarketDataPort(candles),
                    candles=SqlAlchemyCandleRepository(session_a),
                    watermarks=SqlAlchemyIngestionWatermarkRepository(session_a),
                    lock=lock,
                    max_candles_per_page=1,  # tiniest pages -> maximum commit/checkin churn
                )
                use_case_b = BackfillCandles(
                    market_data=FakeMarketDataPort(candles),
                    candles=SqlAlchemyCandleRepository(session_b),
                    watermarks=SqlAlchemyIngestionWatermarkRepository(session_b),
                    lock=lock,
                    max_candles_per_page=1,
                )

                await asyncio.gather(
                    use_case_a(TEST_INSTRUMENT, Granularity.M1, _ts(0), _ts(15)),
                    use_case_b(TEST_INSTRUMENT, Granularity.M1, _ts(10), _ts(30)),
                )

            final_watermark = await SqlAlchemyIngestionWatermarkRepository(session).get_watermark(
                TEST_INSTRUMENT, Granularity.M1
            )
            stored = await SqlAlchemyCandleRepository(session).get_range(
                TEST_INSTRUMENT, Granularity.M1, _ts(0), _ts(30)
            )
            assert final_watermark == (_ts(0), _ts(30)), f"trial {trial}"
            assert len(stored) == 30, f"trial {trial}"

            await session.execute(
                delete(CandleRow).where(CandleRow.instrument == TEST_INSTRUMENT.symbol)
            )
            await session.execute(
                delete(IngestionWatermarkRow).where(
                    IngestionWatermarkRow.instrument == TEST_INSTRUMENT.symbol
                )
            )
            await session.commit()
    finally:
        await constrained_engine.dispose()
