"""FX-38 Part A: bounded, deterministic discovery of each research
instrument's actual earliest available OANDA candle, per granularity
(H1, H4) -- not a presumed/hardcoded 2005 or 2006 start date.

Confirmed live before writing this (EUR/USD H1): a 1995 probe window
returns zero candles (no error -- OANDA just returns an empty
`candles` array for a range with nothing in it), a 2004 probe window
returns a handful of very low-volume candles (a real but sparse/thin
early era), and a 2010 probe window already looks like normal full
density. This script finds the exact boundary via binary search
rather than eyeballing more probe windows by hand.

Approach: binary search on the boundary between "empty" and "has at
least one candle" over `[LOWER_BOUND, hi)`, where `LOWER_BOUND` is a
hardcoded, deliberately absurd date (1990-01-01 -- OANDA's own
platform didn't exist yet; the 1995 probe above already confirms
empty) and `hi` is each series' OWN currently recorded earliest
ingestion watermark (FX-26/30) -- reusing existing infrastructure
rather than hardcoding "2016-09-19", and guaranteed non-empty since
it's already backfilled. Each probe queries a `PROBE_WINDOW_DAYS`-wide
range via the existing, unmodified `OandaMarketDataAdapter.
get_candles(start, end)` -- well under OANDA's 5000-candle cap even at
H1 (60 days * 24 = 1440), so `CandleRangeTooLargeError` never
triggers.

After the search converges to a <=2-day window, one final wider query
(`EXTRACTION_WINDOW_DAYS`) extracts the EXACT earliest candle's own
`start_time` -- the binary search itself only narrows to day
resolution -- and its response is reused to compute a density ratio
for the opening era (candles actually returned vs. a rough weekday-
hours estimate), addressing Part A's "any obvious provider gaps near
the beginning" requirement without a second round-trip.

Sanity check, not just assumed: this whole approach assumes OANDA's
earliest-data boundary is a genuine step function (once data exists,
it continues) rather than an isolated earlier fragment. Verified per
series, not just asserted: after finding the boundary, this script
also probes a window a full year before it (must still be empty) as a
monotonicity spot-check, and reports if that assumption is violated
rather than silently trusting it.

Run:
    uv run python scripts/discover_historical_coverage.py

Requires:
    - `docker compose up -d db` (research dataset already backfilled --
      reads each series' OWN watermark as the binary search's known-good
      upper bound)
    - `OANDA_API_KEY` configured in `.env`
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker

from forex_agent.apps.settings import get_settings
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.broker_oanda.market_data_adapter import OandaMarketDataAdapter
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

LOWER_BOUND = datetime(1990, 1, 1, tzinfo=UTC)
PROBE_WINDOW_DAYS = 60
EXTRACTION_WINDOW_DAYS = 90
DAY_RESOLUTION = timedelta(days=2)  # binary search stops once the gap is this small

# Rough weekday-hours-only expected candle counts per calendar day, used
# only to characterize density (not to classify individual gaps -- that's
# check_research_dataset_gaps.py's job). 5/7 of days are trading days.
_EXPECTED_PER_DAY = {Granularity.H1: 24 * 5 / 7, Granularity.H4: 6 * 5 / 7}


@dataclass
class Boundary:
    instrument: Instrument
    granularity: Granularity
    earliest_candle: UtcTimestamp | None
    monotonicity_holds: bool
    opening_era_density: float | None  # fraction of _EXPECTED_PER_DAY actually seen


async def _has_any_candle(
    adapter: OandaMarketDataAdapter,
    instrument: Instrument,
    granularity: Granularity,
    start: datetime,
) -> bool:
    end = min(start + timedelta(days=PROBE_WINDOW_DAYS), datetime.now(UTC))
    candles = await adapter.get_candles(
        instrument, granularity, UtcTimestamp(start), UtcTimestamp(end)
    )
    return len(candles) > 0


async def _discover(
    adapter: OandaMarketDataAdapter,
    instrument: Instrument,
    granularity: Granularity,
    known_good_upper: datetime,
) -> Boundary:
    lo, hi = LOWER_BOUND, known_good_upper
    if not await _has_any_candle(adapter, instrument, granularity, lo):
        pass  # expected: LOWER_BOUND itself must be empty for the search to be valid
    else:
        raise RuntimeError(
            f"{instrument.symbol} {granularity.value}: LOWER_BOUND {lo.date()} unexpectedly "
            "has candles -- the hardcoded 1990 bound is no longer safely before all data; "
            "widen it rather than trusting this result"
        )

    while hi - lo > DAY_RESOLUTION:
        mid = lo + (hi - lo) / 2
        if await _has_any_candle(adapter, instrument, granularity, mid):
            hi = mid
        else:
            lo = mid

    # Final wider query straddling the converged boundary to extract the
    # exact earliest candle and, from the same response, a density read
    # on the opening era.
    window_end = min(hi + timedelta(days=EXTRACTION_WINDOW_DAYS), datetime.now(UTC))
    candles = await adapter.get_candles(
        instrument, granularity, UtcTimestamp(lo), UtcTimestamp(window_end)
    )
    if not candles:
        raise RuntimeError(
            f"{instrument.symbol} {granularity.value}: binary search converged but the final "
            "extraction window returned nothing -- boundary logic invariant violated"
        )
    earliest = min((c.start_time for c in candles), key=lambda ts: ts.value)

    # Monotonicity spot-check: a full year before the discovered earliest
    # candle must still be empty.
    year_before = earliest.value - timedelta(days=365)
    monotonicity_holds = not (
        year_before >= LOWER_BOUND
        and await _has_any_candle(adapter, instrument, granularity, year_before)
    )

    span_days = (window_end - earliest.value).days or 1
    expected = _EXPECTED_PER_DAY[granularity] * span_days
    density = len(candles) / expected if expected > 0 else None

    return Boundary(instrument, granularity, earliest, monotonicity_holds, density)


async def main() -> None:
    settings = get_settings()
    if not settings.oanda_api_key:
        raise SystemExit("OANDA_API_KEY not configured -- set it in .env")

    session_factory = async_sessionmaker(bind=get_engine())
    adapter = OandaMarketDataAdapter(
        api_key=settings.oanda_api_key, base_url=settings.oanda_api_base_url
    )
    try:
        async with session_factory() as session:
            watermarks = SqlAlchemyIngestionWatermarkRepository(session)
            results: list[Boundary] = []
            for instrument in INSTRUMENTS:
                for granularity in GRANULARITIES:
                    watermark = await watermarks.get_watermark(instrument, granularity)
                    if watermark is None:
                        print(
                            f"{instrument.symbol} {granularity.value}: no watermark -- "
                            "not backfilled yet, skipping discovery"
                        )
                        continue
                    known_earliest, _ = watermark
                    print(
                        f"{instrument.symbol} {granularity.value}: binary searching "
                        f"[{LOWER_BOUND.date()}, {known_earliest.value.date()}) ..."
                    )
                    boundary = await _discover(
                        adapter, instrument, granularity, known_earliest.value
                    )
                    results.append(boundary)
                    density_str = (
                        f"{boundary.opening_era_density:.1%}"
                        if boundary.opening_era_density is not None
                        else "n/a"
                    )
                    print(
                        f"  -> earliest candle: {boundary.earliest_candle.value.isoformat()}"  # type: ignore[union-attr]
                        f" | monotonicity holds: {boundary.monotonicity_holds}"
                        f" | opening-era density (~{EXTRACTION_WINDOW_DAYS}d): {density_str}"
                    )

        print()
        print("### Summary\n")
        print("| Instrument | Granularity | Earliest candle | Monotonic | Opening density |")
        print("|---|---|---|---|---|")
        for b in results:
            density_str = (
                f"{b.opening_era_density:.1%}" if b.opening_era_density is not None else "n/a"
            )
            earliest_str = b.earliest_candle.value.isoformat() if b.earliest_candle else "n/a"
            print(
                f"| {b.instrument.symbol} | {b.granularity.value} | {earliest_str} | "
                f"{b.monotonicity_holds} | {density_str} |"
            )
    finally:
        await adapter.aclose()


if __name__ == "__main__":
    asyncio.run(main())
