"""Research dataset build.

Backfills `YEARS_OF_HISTORY` years of H1/H4 candles for the five research
instruments (EUR/USD, GBP/USD, USD/JPY, USD/CAD, XAU/USD) via FX-26's
`BackfillCandles`, against a live Postgres and the real OANDA practice API.

This wires up already-tested machinery (`BackfillCandles`,
`SqlAlchemyCandleRepository`, `SqlAlchemyIngestionWatermarkRepository`,
`OandaMarketDataAdapter`) rather than adding new behaviour, so it has no
dedicated test suite of its own -- same precedent as `apps/api/main.py`'s
composition wiring.

XAU/USD needs no domain change: `Instrument.base_currency` validation only
requires a 3-letter uppercase code (`require_currency_code`), and "XAU" is
gold's real ISO 4217 code -- confirmed live against the OANDA practice API
before writing this script.

Safe to re-run or resume after an interruption: `BackfillCandles` is fully
resumable via its per-(instrument, granularity) ingestion watermark
(FX-26) -- an interrupted run picks up exactly where it left off, and
already-covered pages are never re-fetched or duplicated.

Run:
    uv run python scripts/build_research_dataset.py

Requires:
    - `docker compose up -d db` (and `alembic upgrade head` already applied)
    - `OANDA_API_KEY` configured in `.env`
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import async_sessionmaker

from forex_agent.application.use_cases.backfill_candles import BackfillCandles
from forex_agent.apps.settings import get_settings
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.broker_oanda.market_data_adapter import OandaMarketDataAdapter
from forex_agent.infrastructure.db.backfill_lock import PostgresBackfillLock
from forex_agent.infrastructure.db.candle_repository import SqlAlchemyCandleRepository
from forex_agent.infrastructure.db.ingestion_watermark_repository import (
    SqlAlchemyIngestionWatermarkRepository,
)
from forex_agent.infrastructure.db.session import get_engine, get_lock_engine

INSTRUMENTS = [
    Instrument(base_currency="EUR", quote_currency="USD"),
    Instrument(base_currency="GBP", quote_currency="USD"),
    Instrument(base_currency="USD", quote_currency="JPY"),
    Instrument(base_currency="USD", quote_currency="CAD"),
    Instrument(base_currency="XAU", quote_currency="USD"),
]
GRANULARITIES = [Granularity.H1, Granularity.H4]
YEARS_OF_HISTORY = 10


async def main() -> None:
    settings = get_settings()
    if not settings.oanda_api_key:
        raise SystemExit("OANDA_API_KEY not configured -- set it in .env")

    end = UtcTimestamp(datetime.now(UTC).replace(microsecond=0))
    start = UtcTimestamp(end.value.replace(year=end.value.year - YEARS_OF_HISTORY))

    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    market_data = OandaMarketDataAdapter(
        api_key=settings.oanda_api_key, base_url=settings.oanda_api_base_url
    )
    try:
        async with session_factory() as session:
            backfill = BackfillCandles(
                market_data=market_data,
                candles=SqlAlchemyCandleRepository(session),
                watermarks=SqlAlchemyIngestionWatermarkRepository(session),
                # Deliberately get_lock_engine(), NOT get_engine() -- see
                # that function's own docstring (FX-31H): sharing a pool
                # between the lock and the candles/watermarks session
                # can deadlock under concurrent backfills for the same
                # series. This script runs sequentially today, so it's
                # not at risk in practice, but the composition itself
                # should still be correct, not correct-by-accident.
                lock=PostgresBackfillLock(get_lock_engine()),
            )
            for instrument in INSTRUMENTS:
                for granularity in GRANULARITIES:
                    print(
                        f"{instrument.symbol} {granularity.value}: backfilling "
                        f"[{start.value.isoformat()}, {end.value.isoformat()}) ..."
                    )
                    result = await backfill(instrument, granularity, start, end)
                    print(
                        f"  -> {result.pages_fetched} pages, "
                        f"{result.candles_written} candles written, covered "
                        f"[{result.earliest_ingested.value.isoformat()}, "
                        f"{result.latest_ingested.value.isoformat()})"
                    )
    finally:
        await market_data.aclose()


if __name__ == "__main__":
    asyncio.run(main())
