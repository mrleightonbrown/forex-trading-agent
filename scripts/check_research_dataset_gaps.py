"""Gap-check pass over the research dataset (`build_research_dataset.py`).

`find_gaps`/`DetectDataGaps` (FX-8/FX-26) are deliberately calendar-unaware
-- see `domain/candle_gaps.py`'s own docstring: "Callers should pass ranges
already known to be within a trading session." A raw 10-year range is NOT
such a range: it spans thousands of weekend market closures, which
`find_gaps` has no way to distinguish from genuine missing data.

This script is the caller-side responsibility that docstring describes: it
runs `DetectDataGaps` over each series' full backfilled range, then filters
out timestamps that fall in the standard forex weekly closure (Friday
17:00 America/New_York to Sunday 17:00 America/New_York) before reporting
anything as a real gap. This reuses the same NY-17:00 session boundary the
rest of this codebase already anchors to (FX-24's `dailyAlignment=17`/
`alignmentTimezone=America/New_York`, `candle_boundary`) -- not a new
convention invented for this script.

Deliberately NOT filtered: holidays (Christmas, New Year's, etc.) -- this
codebase has no holiday calendar (see `candle_gaps.py`'s own documented
scope limitation), so a holiday closure will still be reported here as an
"unexplained" gap. That's a known, named limitation of this report, not a
bug in it -- each remaining gap needs a human glance to tell a holiday
apart from a genuine data-quality issue. This script does not attempt that
classification itself.

Run:
    uv run python scripts/check_research_dataset_gaps.py

Requires:
    - `docker compose up -d db` (and `alembic upgrade head` already applied)
    - The research dataset already backfilled (`build_research_dataset.py`)
"""

from __future__ import annotations

import asyncio
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import async_sessionmaker

from forex_agent.application.use_cases.detect_data_gaps import DetectDataGaps
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.candle_repository import SqlAlchemyCandleRepository
from forex_agent.infrastructure.db.ingestion_watermark_repository import (
    SqlAlchemyIngestionWatermarkRepository,
)
from forex_agent.infrastructure.db.session import get_engine

INSTRUMENTS = [
    Instrument(base_currency="EUR", quote_currency="USD"),
    Instrument(base_currency="GBP", quote_currency="USD"),
    Instrument(base_currency="USD", quote_currency="JPY"),
    Instrument(base_currency="USD", quote_currency="CAD"),
    Instrument(base_currency="XAU", quote_currency="USD"),
]
GRANULARITIES = [Granularity.H1, Granularity.H4]

_NY = ZoneInfo("America/New_York")
_SAMPLE_SIZE = 20


def _is_weekly_closure(ts: UtcTimestamp) -> bool:
    """True if `ts` falls within the standard forex weekly closure:
    Friday 17:00 NY to Sunday 17:00 NY. Same boundary this codebase
    already anchors day-aligned candles to (FX-24)."""
    ny = ts.value.astimezone(_NY)
    weekday = ny.weekday()  # Monday=0 ... Sunday=6
    if weekday == 5:  # Saturday: always closed
        return True
    if weekday == 4 and ny.hour >= 17:  # Friday from 17:00 NY
        return True
    return weekday == 6 and ny.hour < 17  # Sunday before 17:00 NY


async def main() -> None:
    session_factory = async_sessionmaker(bind=get_engine())
    async with session_factory() as session:
        watermarks = SqlAlchemyIngestionWatermarkRepository(session)
        detect_gaps = DetectDataGaps(candles=SqlAlchemyCandleRepository(session))

        total_raw = 0
        total_unexplained = 0
        unexplained_by_series: dict[str, list[UtcTimestamp]] = {}

        for instrument in INSTRUMENTS:
            for granularity in GRANULARITIES:
                key = f"{instrument.symbol} {granularity.value}"
                watermark = await watermarks.get_watermark(instrument, granularity)
                if watermark is None:
                    print(f"{key}: no watermark -- not backfilled, skipping")
                    continue
                earliest, latest = watermark

                raw_gaps = await detect_gaps(instrument, granularity, earliest, latest)
                unexplained = [ts for ts in raw_gaps if not _is_weekly_closure(ts)]

                total_raw += len(raw_gaps)
                total_unexplained += len(unexplained)
                if unexplained:
                    unexplained_by_series[key] = unexplained

                print(
                    f"{key}: {len(raw_gaps)} raw missing candle slots, "
                    f"{len(unexplained)} unexplained after weekly-closure filtering"
                )

        print()
        print(f"TOTAL: {total_raw} raw, {total_unexplained} unexplained across all series")

        if unexplained_by_series:
            print()
            print("Unexplained gaps (sample; full list not printed if large):")
            for key, gaps in unexplained_by_series.items():
                print(f"  {key}: {len(gaps)} unexplained")
                for ts in gaps[:_SAMPLE_SIZE]:
                    print(f"    {ts.value.isoformat()}")
                if len(gaps) > _SAMPLE_SIZE:
                    print(f"    ... and {len(gaps) - _SAMPLE_SIZE} more")


if __name__ == "__main__":
    asyncio.run(main())
