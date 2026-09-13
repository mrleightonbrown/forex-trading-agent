"""SQLAlchemy implementation of `CandleRepository` (FX-5, `get_range` FX-7)."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.models.candle import CandleRow

_CONFLICT_KEY = ("instrument", "granularity", "start_time")
_UPDATABLE_COLUMNS = (
    "bid_open",
    "bid_high",
    "bid_low",
    "bid_close",
    "ask_open",
    "ask_high",
    "ask_low",
    "ask_close",
    "volume",
    "is_finalized",
)


class SqlAlchemyCandleRepository:
    """Implements `CandleRepository` via a Postgres `ON CONFLICT DO UPDATE`
    upsert, keyed on the `candles` table's unique constraint — this is what
    makes calling `upsert_many` with the same candles repeatedly safe."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_many(self, candles: list[Candle]) -> int:
        if not candles:
            return 0

        stmt = pg_insert(CandleRow).values([_row_values(c) for c in candles])
        stmt = stmt.on_conflict_do_update(
            index_elements=_CONFLICT_KEY,
            set_={column: getattr(stmt.excluded, column) for column in _UPDATABLE_COLUMNS},
        )
        await self._session.execute(stmt)
        await self._session.commit()
        return len(candles)

    async def get_range(
        self,
        instrument: Instrument,
        granularity: Granularity,
        start: UtcTimestamp,
        end: UtcTimestamp,
    ) -> list[Candle]:
        stmt = (
            select(CandleRow)
            .where(
                CandleRow.instrument == instrument.symbol,
                CandleRow.granularity == granularity.value,
                CandleRow.start_time >= start.value,
                CandleRow.start_time < end.value,
            )
            .order_by(CandleRow.start_time)
        )
        result = await self._session.execute(stmt)
        return [_to_domain(instrument, granularity, row) for row in result.scalars().all()]


def _to_domain(instrument: Instrument, granularity: Granularity, row: CandleRow) -> Candle:
    return Candle(
        instrument=instrument,
        granularity=granularity,
        start_time=UtcTimestamp(row.start_time),
        bid=Ohlc(open=row.bid_open, high=row.bid_high, low=row.bid_low, close=row.bid_close),
        ask=Ohlc(open=row.ask_open, high=row.ask_high, low=row.ask_low, close=row.ask_close),
        volume=row.volume,
        is_finalized=row.is_finalized,
    )


def _row_values(candle: Candle) -> dict[str, object]:
    return {
        "instrument": candle.instrument.symbol,
        "granularity": candle.granularity.value,
        "start_time": candle.start_time.value,
        "bid_open": candle.bid.open,
        "bid_high": candle.bid.high,
        "bid_low": candle.bid.low,
        "bid_close": candle.bid.close,
        "ask_open": candle.ask.open,
        "ask_high": candle.ask.high,
        "ask_low": candle.ask.low,
        "ask_close": candle.ask.close,
        "volume": candle.volume,
        "is_finalized": candle.is_finalized,
    }
