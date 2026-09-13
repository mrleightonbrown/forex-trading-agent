"""SQLAlchemy implementation of `CandleRepository` (FX-5)."""

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from forex_agent.domain.candle import Candle
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
