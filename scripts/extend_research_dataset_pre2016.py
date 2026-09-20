"""FX-38 Part B: extend the research dataset backward to each series'
actual earliest OANDA candle, as discovered by
`discover_historical_coverage.py` (Part A) -- not a presumed/manufactured
common start date. Per-instrument, per-granularity start dates below are
transcribed directly from that script's own recorded output, not
re-guessed here.

Reuses the SAME `BackfillCandles` (FX-26) wiring as
`build_research_dataset.py`, unmodified. `BackfillCandles` already
handles "extend an existing watermark backward" as its own first-class
case (`_extend_backward`, descending page order, watermark's `earliest`
only ever retreats into contiguous already-verified territory) -- this
script just calls it with each series' true earliest boundary instead of
"10 years ago". The existing 2016-2026 dataset is untouched: `end` here
is `datetime.now(UTC)`, so any call also cheaply re-extends `latest`
forward to now (same as re-running `build_research_dataset.py`), but the
already-covered middle of the range is never re-fetched (idempotent,
resumable, per FX-26's own watermark semantics).

Run:
    uv run python scripts/extend_research_dataset_pre2016.py

Requires:
    - `docker compose up -d db` (existing research dataset already
      loaded -- this only extends it backward)
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

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")
GBP_USD = Instrument(base_currency="GBP", quote_currency="USD")
USD_JPY = Instrument(base_currency="USD", quote_currency="JPY")
USD_CAD = Instrument(base_currency="USD", quote_currency="CAD")
XAU_USD = Instrument(base_currency="XAU", quote_currency="USD")

# Transcribed verbatim from discover_historical_coverage.py's own printed
# output (2026-09-19 run against the live OANDA practice API) -- the
# discovered earliest candle per (instrument, granularity), not a
# recomputation and not an assumption.
EARLIEST_AVAILABLE: dict[tuple[Instrument, Granularity], datetime] = {
    (EUR_USD, Granularity.H1): datetime(2002, 5, 6, 20, 0, tzinfo=UTC),
    (EUR_USD, Granularity.H4): datetime(2002, 5, 7, 17, 0, tzinfo=UTC),
    (GBP_USD, Granularity.H1): datetime(2002, 5, 6, 20, 0, tzinfo=UTC),
    (GBP_USD, Granularity.H4): datetime(2002, 5, 7, 17, 0, tzinfo=UTC),
    (USD_JPY, Granularity.H1): datetime(2002, 5, 6, 20, 0, tzinfo=UTC),
    (USD_JPY, Granularity.H4): datetime(2002, 5, 7, 17, 0, tzinfo=UTC),
    (USD_CAD, Granularity.H1): datetime(2002, 5, 7, 20, 0, tzinfo=UTC),
    (USD_CAD, Granularity.H4): datetime(2002, 5, 8, 17, 0, tzinfo=UTC),
    (XAU_USD, Granularity.H1): datetime(2006, 3, 19, 20, 0, tzinfo=UTC),
    (XAU_USD, Granularity.H4): datetime(2006, 3, 19, 22, 0, tzinfo=UTC),
}


async def main() -> None:
    settings = get_settings()
    if not settings.oanda_api_key:
        raise SystemExit("OANDA_API_KEY not configured -- set it in .env")

    end = UtcTimestamp(datetime.now(UTC).replace(microsecond=0))

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
                lock=PostgresBackfillLock(get_lock_engine()),  # FX-31H: dedicated pool
            )
            for (instrument, granularity), earliest in EARLIEST_AVAILABLE.items():
                start = UtcTimestamp(earliest)
                print(
                    f"{instrument.symbol} {granularity.value}: extending to "
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
