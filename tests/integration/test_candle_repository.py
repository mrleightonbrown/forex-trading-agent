"""Regression tests for FX-5's idempotent candle upsert.

CLAUDE.md requires protection against "duplicate events" and "provider
duplication" — this is exactly what re-running candle ingestion risks
without the unique constraint + ON CONFLICT DO UPDATE this repository uses.

Requires a live Postgres with the FX-5 migration applied — run
`docker compose up -d db && uv run alembic upgrade head` first.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.domain.candle import Candle
from forex_agent.domain.candle_source import CandleSource
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.candle_repository import SqlAlchemyCandleRepository
from forex_agent.infrastructure.db.models.candle import CandleRow
from forex_agent.infrastructure.db.session import get_engine

# A currency pair unlikely to ever be real, to keep test rows unambiguous.
TEST_INSTRUMENT = Instrument(base_currency="ZZZ", quote_currency="YYY")
START = UtcTimestamp(datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC))


_SPREAD = Decimal("0.0002")


def _candle(
    *,
    bid_close: str,
    is_finalized: bool,
    start_time: UtcTimestamp = START,
    source: CandleSource = CandleSource.NATIVE,
) -> Candle:
    bid_close_decimal = Decimal(bid_close)
    return Candle(
        instrument=TEST_INSTRUMENT,
        granularity=Granularity.M1,
        start_time=start_time,
        bid=Ohlc(
            open=Decimal("1.0000"),
            high=Decimal("1.0010"),
            low=Decimal("0.9990"),
            close=bid_close_decimal,
        ),
        ask=Ohlc(
            open=Decimal("1.0002"),
            high=Decimal("1.0012"),
            low=Decimal("0.9992"),
            close=bid_close_decimal + _SPREAD,
        ),
        volume=10,
        is_finalized=is_finalized,
        source=source,
    )


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    async with session_factory() as db_session:
        yield db_session

    async with session_factory() as cleanup_session:
        await cleanup_session.execute(
            delete(CandleRow).where(CandleRow.instrument == TEST_INSTRUMENT.symbol)
        )
        await cleanup_session.commit()


async def _row_count(session: AsyncSession) -> int:
    result = await session.execute(
        select(CandleRow).where(CandleRow.instrument == TEST_INSTRUMENT.symbol)
    )
    return len(result.scalars().all())


@pytest.mark.asyncio
async def test_upsert_many_inserts_new_candles(session: AsyncSession) -> None:
    repo = SqlAlchemyCandleRepository(session)

    written = await repo.upsert_many([_candle(bid_close="1.0005", is_finalized=False)])

    assert written == 1
    assert await _row_count(session) == 1


@pytest.mark.asyncio
async def test_upsert_many_is_idempotent_for_identical_candle(session: AsyncSession) -> None:
    repo = SqlAlchemyCandleRepository(session)
    candle = _candle(bid_close="1.0005", is_finalized=False)

    await repo.upsert_many([candle])
    await repo.upsert_many([candle])

    assert await _row_count(session) == 1


@pytest.mark.asyncio
async def test_upsert_many_updates_existing_candle_in_place(session: AsyncSession) -> None:
    """Simulates a forming candle later finalizing: same
    (instrument, granularity, start_time), different values."""
    repo = SqlAlchemyCandleRepository(session)

    await repo.upsert_many([_candle(bid_close="1.0003", is_finalized=False)])
    await repo.upsert_many([_candle(bid_close="1.0009", is_finalized=True)])

    assert await _row_count(session) == 1

    result = await session.execute(
        select(CandleRow).where(CandleRow.instrument == TEST_INSTRUMENT.symbol)
    )
    row = result.scalar_one()
    assert row.bid_close == Decimal("1.0009")
    assert row.is_finalized is True


@pytest.mark.asyncio
async def test_get_range_filters_and_orders_by_start_time(session: AsyncSession) -> None:
    repo = SqlAlchemyCandleRepository(session)
    t0, t1, t2 = (
        START,
        UtcTimestamp(START.value.replace(minute=1)),
        UtcTimestamp(START.value.replace(minute=2)),
    )
    await repo.upsert_many(
        [
            _candle(bid_close="1.0002", is_finalized=True, start_time=t2),
            _candle(bid_close="1.0000", is_finalized=True, start_time=t0),
            _candle(bid_close="1.0001", is_finalized=True, start_time=t1),
        ]
    )

    result = await repo.get_range(TEST_INSTRUMENT, Granularity.M1, t0, t2)

    assert [c.start_time for c in result] == [t0, t1]  # end is exclusive
    assert [c.bid.close for c in result] == [Decimal("1.0000"), Decimal("1.0001")]


@pytest.mark.asyncio
async def test_get_range_returns_empty_list_when_nothing_matches(session: AsyncSession) -> None:
    repo = SqlAlchemyCandleRepository(session)

    result = await repo.get_range(TEST_INSTRUMENT, Granularity.M1, START, START)

    assert result == []


@pytest.mark.asyncio
async def test_source_round_trips_through_upsert_and_get_range(session: AsyncSession) -> None:
    repo = SqlAlchemyCandleRepository(session)

    await repo.upsert_many([_candle(bid_close="1.0005", is_finalized=True)])

    result = await repo.get_range(
        TEST_INSTRUMENT, Granularity.M1, START, UtcTimestamp(START.value.replace(minute=1))
    )

    assert len(result) == 1
    assert result[0].source is CandleSource.NATIVE


@pytest.mark.asyncio
async def test_get_range_source_none_returns_all_provenances(session: AsyncSession) -> None:
    """FX-27: `source=None` is the explicit "all sources" choice, not an
    accidental default -- both NATIVE and AGGREGATED rows for the same
    slot come back together."""
    repo = SqlAlchemyCandleRepository(session)
    await repo.upsert_many(
        [
            _candle(bid_close="1.0001", is_finalized=True, source=CandleSource.NATIVE),
            _candle(bid_close="1.0009", is_finalized=True, source=CandleSource.AGGREGATED),
        ]
    )

    result = await repo.get_range(
        TEST_INSTRUMENT,
        Granularity.M1,
        START,
        UtcTimestamp(START.value.replace(minute=1)),
        source=None,
    )

    assert {c.source for c in result} == {CandleSource.NATIVE, CandleSource.AGGREGATED}


@pytest.mark.asyncio
async def test_get_range_source_native_filters_to_native_only(session: AsyncSession) -> None:
    repo = SqlAlchemyCandleRepository(session)
    await repo.upsert_many(
        [
            _candle(bid_close="1.0001", is_finalized=True, source=CandleSource.NATIVE),
            _candle(bid_close="1.0009", is_finalized=True, source=CandleSource.AGGREGATED),
        ]
    )

    result = await repo.get_range(
        TEST_INSTRUMENT,
        Granularity.M1,
        START,
        UtcTimestamp(START.value.replace(minute=1)),
        source=CandleSource.NATIVE,
    )

    assert len(result) == 1
    assert result[0].source is CandleSource.NATIVE
    assert result[0].bid.close == Decimal("1.0001")


@pytest.mark.asyncio
async def test_get_range_source_aggregated_filters_to_aggregated_only(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyCandleRepository(session)
    await repo.upsert_many(
        [
            _candle(bid_close="1.0001", is_finalized=True, source=CandleSource.NATIVE),
            _candle(bid_close="1.0009", is_finalized=True, source=CandleSource.AGGREGATED),
        ]
    )

    result = await repo.get_range(
        TEST_INSTRUMENT,
        Granularity.M1,
        START,
        UtcTimestamp(START.value.replace(minute=1)),
        source=CandleSource.AGGREGATED,
    )

    assert len(result) == 1
    assert result[0].source is CandleSource.AGGREGATED
    assert result[0].bid.close == Decimal("1.0009")


@pytest.mark.asyncio
async def test_native_and_aggregated_candles_coexist_without_collision(
    session: AsyncSession,
) -> None:
    """FX-24: same instrument/granularity/start_time, different `source`
    -- must NOT collide/overwrite each other, unlike two candles that
    only differ by content (which upsert intentionally treats as the
    same logical row, per test_upsert_many_updates_existing_candle_in_place
    above)."""
    repo = SqlAlchemyCandleRepository(session)

    await repo.upsert_many(
        [_candle(bid_close="1.0001", is_finalized=True, source=CandleSource.NATIVE)]
    )
    await repo.upsert_many(
        [_candle(bid_close="1.0009", is_finalized=True, source=CandleSource.AGGREGATED)]
    )

    assert await _row_count(session) == 2

    result = await repo.get_range(
        TEST_INSTRUMENT, Granularity.M1, START, UtcTimestamp(START.value.replace(minute=1))
    )
    assert {c.source for c in result} == {CandleSource.NATIVE, CandleSource.AGGREGATED}
    assert {c.bid.close for c in result} == {Decimal("1.0001"), Decimal("1.0009")}
