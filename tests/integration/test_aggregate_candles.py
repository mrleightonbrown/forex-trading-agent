"""End-to-end check that FX-7's AggregateCandles use case reads M1 candles
back out of storage, aggregates them, and persists the result — the
persistence half `aggregate_candles` (the pure domain function) deliberately
left out.

Requires a live Postgres with the FX-5 migration applied.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.application.use_cases.aggregate_candles import AggregateCandles
from forex_agent.domain.candle import Candle
from forex_agent.domain.candle_source import CandleSource
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.candle_repository import SqlAlchemyCandleRepository
from forex_agent.infrastructure.db.models.candle import CandleRow
from forex_agent.infrastructure.db.session import get_engine

TEST_INSTRUMENT = Instrument(base_currency="ZZZ", quote_currency="WWW")
WINDOW_START = UtcTimestamp(datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC))
WINDOW_END = UtcTimestamp(datetime(2026, 1, 1, 0, 5, 0, tzinfo=UTC))


def _m1(minute: int, close: str, *, source: CandleSource = CandleSource.NATIVE) -> Candle:
    flat = Ohlc(
        open=Decimal("1.0000"), high=Decimal("1.0010"), low=Decimal("0.9990"), close=Decimal(close)
    )
    return Candle(
        instrument=TEST_INSTRUMENT,
        granularity=Granularity.M1,
        start_time=UtcTimestamp(datetime(2026, 1, 1, 0, minute, 0, tzinfo=UTC)),
        bid=flat,
        ask=flat,
        volume=10,
        is_finalized=True,
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


@pytest.mark.asyncio
async def test_aggregate_candles_reads_aggregates_and_persists(session: AsyncSession) -> None:
    repo = SqlAlchemyCandleRepository(session)
    await repo.upsert_many([_m1(m, f"1.000{m}") for m in range(5)])
    use_case = AggregateCandles(candles=repo)

    written = await use_case(
        TEST_INSTRUMENT, Granularity.M1, Granularity.M5, WINDOW_START, WINDOW_END
    )

    assert written == 1
    result = await repo.get_range(TEST_INSTRUMENT, Granularity.M5, WINDOW_START, WINDOW_END)
    assert len(result) == 1
    assert result[0].bid.open == Decimal("1.0000")
    assert result[0].bid.close == Decimal("1.0004")
    assert result[0].volume == 50


@pytest.mark.asyncio
async def test_aggregate_candles_is_safe_to_repeat(session: AsyncSession) -> None:
    repo = SqlAlchemyCandleRepository(session)
    await repo.upsert_many([_m1(m, f"1.000{m}") for m in range(5)])
    use_case = AggregateCandles(candles=repo)

    await use_case(TEST_INSTRUMENT, Granularity.M1, Granularity.M5, WINDOW_START, WINDOW_END)
    await use_case(TEST_INSTRUMENT, Granularity.M1, Granularity.M5, WINDOW_START, WINDOW_END)

    result = await repo.get_range(TEST_INSTRUMENT, Granularity.M5, WINDOW_START, WINDOW_END)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_aggregate_candles_skips_incomplete_trailing_bucket(session: AsyncSession) -> None:
    repo = SqlAlchemyCandleRepository(session)
    await repo.upsert_many([_m1(m, f"1.000{m}") for m in range(3)])  # only 3 of 5 needed
    use_case = AggregateCandles(candles=repo)

    written = await use_case(
        TEST_INSTRUMENT, Granularity.M1, Granularity.M5, WINDOW_START, WINDOW_END
    )

    assert written == 0


@pytest.mark.asyncio
async def test_aggregate_candles_ignores_preexisting_aggregated_source_candles(
    session: AsyncSession,
) -> None:
    """FX-27: AggregateCandles must read only CandleSource.NATIVE rows.
    If AGGREGATED-source M1 candles happened to exist for this window
    (e.g. from a self-aggregation upstream), they must not be re-read
    and re-aggregated -- only genuine NATIVE M1 candles count."""
    repo = SqlAlchemyCandleRepository(session)
    await repo.upsert_many([_m1(m, f"1.000{m}", source=CandleSource.AGGREGATED) for m in range(5)])
    use_case = AggregateCandles(candles=repo)

    written = await use_case(
        TEST_INSTRUMENT, Granularity.M1, Granularity.M5, WINDOW_START, WINDOW_END
    )

    assert written == 0
