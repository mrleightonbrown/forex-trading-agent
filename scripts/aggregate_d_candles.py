"""FX-46 (preparation step): materializes real `D` (daily) candles for
EUR/USD, GBP/USD, USD/CAD via the existing `AggregateCandles` use case
(FX-7) -- NOT a new data-access path.

No NATIVE `D`-granularity candles have ever been ingested for this
project (confirmed directly via SQL before writing this: `candles`
holds only `H1`/`H4` rows). `H4` candles ARE day-aligned (17:00
`America/New_York`, FX-24/FX-25H) and complete back to ~2002-05 for
all three pairs, so aggregating `H4` -> `D` produces exactly the same
17:00-NY-aligned daily bars FX-46's own "D-bar open" research
convention needs -- `domain.candle_aggregation.aggregate_candles`
drops any bucket whose source candles don't exactly tile it (a
trailing/incomplete/DST-shortened bucket), so no bucket is ever
silently fabricated from partial data.

Idempotent (FX-7's own `upsert_many` contract) -- safe to re-run; every
aggregated row is written with `source=AGGREGATED`, so it can never
collide with a (currently nonexistent) NATIVE `D` row for the same
instrument/start_time.

Run:
    uv run python scripts/aggregate_d_candles.py

Requires:
    - `docker compose up -d db` (H1/H4 candle data already ingested)
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import async_sessionmaker

from forex_agent.application.use_cases.aggregate_candles import AggregateCandles
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.candle_repository import SqlAlchemyCandleRepository
from forex_agent.infrastructure.db.session import get_engine

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")
GBP_USD = Instrument(base_currency="GBP", quote_currency="USD")
USD_CAD = Instrument(base_currency="USD", quote_currency="CAD")
INSTRUMENTS = (EUR_USD, GBP_USD, USD_CAD)

# Wide enough to comfortably bound every pair's own real H4 history
# (earliest ~2002-05-07) through the present; get_range's own [start,
# end) bounds do the real clipping per pair.
_START = UtcTimestamp(datetime(2002, 1, 1, tzinfo=UTC))
_END = UtcTimestamp(datetime.now(UTC))


async def main() -> None:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    async with session_factory() as session:
        repo = SqlAlchemyCandleRepository(session)
        aggregate = AggregateCandles(candles=repo)
        for instrument in INSTRUMENTS:
            written = await aggregate(instrument, Granularity.H4, Granularity.D, _START, _END)
            print(f"{instrument.symbol}: {written} D candles aggregated/upserted from H4")


if __name__ == "__main__":
    asyncio.run(main())
