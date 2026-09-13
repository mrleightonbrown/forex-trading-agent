"""End-to-end check that FX-6's IngestCandles actually lands fetched
candles in the `candles` table via the real repository.

Uses FakeMarketDataPort (no live network) to keep this deterministic and
fast; connectivity to the real OANDA API is separately covered by
test_oanda_market_data_adapter.py. This test's job is proving the
use case wires MarketDataPort's output correctly into CandleRepository —
not proving OANDA connectivity again.

Requires a live Postgres with the FX-5 migration applied.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.application.use_cases.ingest_candles import IngestCandles
from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.candle_repository import SqlAlchemyCandleRepository
from forex_agent.infrastructure.db.models.candle import CandleRow
from forex_agent.infrastructure.db.session import get_engine

TEST_INSTRUMENT = Instrument(base_currency="ZZZ", quote_currency="XXX")
START = UtcTimestamp(datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC))
END = UtcTimestamp(datetime(2026, 1, 1, 0, 5, 0, tzinfo=UTC))


class FakeMarketDataPort:
    """Structurally satisfies `MarketDataPort` — no live network."""

    def __init__(self, candles: list[Candle]) -> None:
        self._candles = candles

    async def get_candles(
        self,
        instrument: Instrument,
        granularity: Granularity,
        start: UtcTimestamp,
        end: UtcTimestamp,
    ) -> list[Candle]:
        return self._candles


def _candle(minute: int) -> Candle:
    return Candle(
        instrument=TEST_INSTRUMENT,
        granularity=Granularity.M1,
        start_time=UtcTimestamp(datetime(2026, 1, 1, 0, minute, 0, tzinfo=UTC)),
        bid=Ohlc(
            open=Decimal("1.0000"),
            high=Decimal("1.0010"),
            low=Decimal("0.9990"),
            close=Decimal("1.0005"),
        ),
        ask=Ohlc(
            open=Decimal("1.0002"),
            high=Decimal("1.0012"),
            low=Decimal("0.9992"),
            close=Decimal("1.0007"),
        ),
        volume=10,
        is_finalized=True,
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
async def test_ingest_candles_persists_fetched_candles(session: AsyncSession) -> None:
    fetched = [_candle(0), _candle(1), _candle(2)]
    use_case = IngestCandles(
        market_data=FakeMarketDataPort(fetched),
        candles=SqlAlchemyCandleRepository(session),
    )

    written = await use_case(TEST_INSTRUMENT, Granularity.M1, START, END)

    assert written == 3
    result = await session.execute(
        select(CandleRow).where(CandleRow.instrument == TEST_INSTRUMENT.symbol)
    )
    assert len(result.scalars().all()) == 3


@pytest.mark.asyncio
async def test_ingest_candles_is_safe_to_repeat(session: AsyncSession) -> None:
    fetched = [_candle(0)]
    use_case = IngestCandles(
        market_data=FakeMarketDataPort(fetched),
        candles=SqlAlchemyCandleRepository(session),
    )

    await use_case(TEST_INSTRUMENT, Granularity.M1, START, END)
    await use_case(TEST_INSTRUMENT, Granularity.M1, START, END)

    result = await session.execute(
        select(CandleRow).where(CandleRow.instrument == TEST_INSTRUMENT.symbol)
    )
    assert len(result.scalars().all()) == 1
