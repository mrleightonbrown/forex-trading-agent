"""FX-38H Part A: objectively determine `earliest_usable_research_candle`
per `(instrument, granularity)` -- distinct from FX-38's own
`earliest_available_candle` (the raw technical first candle OANDA
returns, found by `discover_historical_coverage.py`).

Motivated by external review of FX-38: that story's Part A/B found the
technical start (2002 for the four FX pairs, 2006 for XAU/USD) but its
Part D-F used that raw boundary directly as the holdout period's start,
including a real but sparse ~5%/~15%-density "ramp-up" era (documented
there, not hidden) without an OBJECTIVE rule for where "usable" data
actually begins. This script supplies that rule, applied uniformly and
computed BEFORE any strategy is rerun.

Rule (locked before running, not tuned to produce a particular answer):
a 90-day window is "clean" if, after excluding the standard forex
weekly closure (Friday 17:00 - Sunday 17:00 America/New_York, same
boundary `check_research_dataset_gaps.py` already uses) and, for
XAU/USD's H1 series specifically, its own documented daily settlement
gap (every Mon/Tue/Wed/Thu/Sun at exactly 17:00 NY -- confirmed live in
FX-27H.1, not assumed here), (a) coverage (present / expected) is
>= 95%, AND (b) no single run of consecutive missing expected slots
exceeds 72 hours (3 days) -- catching a prolonged unexplained outage
that a high AGGREGATE coverage ratio alone could still hide.
`earliest_usable_research_candle` is the start of the FIRST 90-day
window such that it and the following 7 windows (8 * 90 = ~2 years)
ALL pass -- "sustained", not a single lucky window.

Reuses the same canonical `candle_boundary` stepping `find_gaps` itself
uses (not `find_gaps` directly -- that revalidates and rescans the
whole candle list every call, wasteful across ~300 windows per series;
this does one O(n) pass to build a start-time set per series, then O(1)
membership checks per expected slot).

Purely a read against the already-backfilled Postgres research dataset
(FX-38 Part B) -- no OANDA calls, no data mutated or deleted.

Run:
    uv run python scripts/determine_usable_history_start.py

Requires:
    - `docker compose up -d db` (FX-38's extended research dataset
      already backfilled)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import async_sessionmaker

from forex_agent.domain.candle_boundary import candle_end_time, candle_start_boundary
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.candle_repository import SqlAlchemyCandleRepository
from forex_agent.infrastructure.db.ingestion_watermark_repository import (
    SqlAlchemyIngestionWatermarkRepository,
)
from forex_agent.infrastructure.db.session import get_engine

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")
GBP_USD = Instrument(base_currency="GBP", quote_currency="USD")
USD_JPY = Instrument(base_currency="USD", quote_currency="JPY")
USD_CAD = Instrument(base_currency="USD", quote_currency="CAD")
XAU_USD = Instrument(base_currency="XAU", quote_currency="USD")
INSTRUMENTS = [EUR_USD, GBP_USD, USD_JPY, USD_CAD, XAU_USD]
GRANULARITIES = [Granularity.H1, Granularity.H4]

_NY = ZoneInfo("America/New_York")

# --- Locked parameters (chosen before running, not tuned afterward) -------
WINDOW_DAYS = 90
COVERAGE_THRESHOLD = Decimal("0.95")
SUSTAINED_WINDOWS = 8  # 8 * 90 days ~= 2 years
MAX_UNEXPLAINED_GAP_HOURS = 72  # 3 days
SCAN_THROUGH = datetime(2018, 1, 1, tzinfo=UTC)  # comfortably past FX-38's own found ~2005/2007
# ---------------------------------------------------------------------------


def _is_weekly_closure(ts: datetime) -> bool:
    ny = ts.astimezone(_NY)
    weekday = ny.weekday()
    if weekday == 5:
        return True
    if weekday == 4 and ny.hour >= 17:
        return True
    return weekday == 6 and ny.hour < 17


def _is_xau_h1_settlement_gap(
    ts: datetime, instrument: Instrument, granularity: Granularity
) -> bool:
    """FX-27H.1's own confirmed finding: XAU/USD H1 has a real, expected
    daily quote gap at exactly 17:00 NY on Sun/Mon/Tue/Wed/Thu (not a
    data-quality issue) -- excluded from "expected" for XAU/USD H1 only,
    matching the granularity FX-27H.1 actually investigated (H4's own
    residual from this was comparatively negligible there)."""
    if instrument is not XAU_USD or granularity is not Granularity.H1:
        return False
    ny = ts.astimezone(_NY)
    return ny.hour == 17 and ny.minute == 0 and ny.weekday() in {6, 0, 1, 2, 3}


@dataclass(frozen=True, slots=True)
class WindowResult:
    start: datetime
    end: datetime
    expected: int
    present: int
    coverage: Decimal
    max_gap_hours: float
    passes: bool


def _evaluate_window(
    window_start: datetime,
    window_end: datetime,
    present_times: set[datetime],
    granularity: Granularity,
    instrument: Instrument,
) -> WindowResult:
    cursor = candle_start_boundary(window_start, granularity)
    expected = 0
    present = 0
    current_gap_start: datetime | None = None
    max_gap_seconds = 0.0
    while cursor < window_end:
        if _is_weekly_closure(cursor) or _is_xau_h1_settlement_gap(cursor, instrument, granularity):
            cursor = candle_end_time(cursor, granularity)
            continue
        expected += 1
        if cursor in present_times:
            present += 1
            current_gap_start = None
        else:
            if current_gap_start is None:
                current_gap_start = cursor
            gap_seconds = (cursor - current_gap_start).total_seconds()
            max_gap_seconds = max(max_gap_seconds, gap_seconds)
        cursor = candle_end_time(cursor, granularity)

    coverage = Decimal(present) / Decimal(expected) if expected > 0 else Decimal(0)
    max_gap_hours = max_gap_seconds / 3600
    passes = coverage >= COVERAGE_THRESHOLD and max_gap_hours <= MAX_UNEXPLAINED_GAP_HOURS
    return WindowResult(
        window_start, window_end, expected, present, coverage, max_gap_hours, passes
    )


def _find_usable_start(
    earliest_available: datetime,
    present_times: set[datetime],
    granularity: Granularity,
    instrument: Instrument,
) -> tuple[datetime | None, list[WindowResult]]:
    windows: list[WindowResult] = []
    cursor = earliest_available
    while cursor < SCAN_THROUGH:
        window_end = cursor + timedelta(days=WINDOW_DAYS)
        windows.append(_evaluate_window(cursor, window_end, present_times, granularity, instrument))
        cursor = window_end

    for i in range(len(windows) - SUSTAINED_WINDOWS + 1):
        if all(w.passes for w in windows[i : i + SUSTAINED_WINDOWS]):
            return windows[i].start, windows
    return None, windows


async def main() -> None:
    session_factory = async_sessionmaker(bind=get_engine())
    async with session_factory() as session:
        watermarks = SqlAlchemyIngestionWatermarkRepository(session)
        repo = SqlAlchemyCandleRepository(session)

        results: dict[tuple[Instrument, Granularity], datetime | None] = {}

        print(
            "| Instrument | Granularity | earliest_available_candle | "
            "earliest_usable_research_candle |"
        )
        print("|---|---|---|---|")
        for instrument in INSTRUMENTS:
            for granularity in GRANULARITIES:
                watermark = await watermarks.get_watermark(instrument, granularity)
                if watermark is None:
                    not_backfilled = "n/a (not backfilled)"
                    print(f"| {instrument.symbol} | {granularity.value} | n/a | {not_backfilled} |")
                    continue
                earliest_ingested, _latest = watermark
                candles = await repo.get_range(
                    instrument,
                    granularity,
                    earliest_ingested,
                    UtcTimestamp(SCAN_THROUGH),
                    source=None,
                )
                present_times = {c.start_time.value for c in candles if c.is_finalized}
                usable_start, _windows = _find_usable_start(
                    earliest_ingested.value, present_times, granularity, instrument
                )
                results[(instrument, granularity)] = usable_start
                usable_str = (
                    usable_start.date().isoformat() if usable_start else "NOT FOUND by SCAN_THROUGH"
                )
                print(
                    f"| {instrument.symbol} | {granularity.value} | "
                    f"{earliest_ingested.value.date().isoformat()} | {usable_str} |"
                )

        print(
            "\n### MultiTimeframeTrendStrategy usable start (later of its own H1/H4 boundaries)\n"
        )
        print("| Instrument | H1 usable | H4 usable | MTT usable (max) |")
        print("|---|---|---|---|")
        for instrument in INSTRUMENTS:
            h1 = results.get((instrument, Granularity.H1))
            h4 = results.get((instrument, Granularity.H4))
            mtt = max(h1, h4) if h1 and h4 else None
            mtt_str = mtt.date().isoformat() if mtt else "n/a"
            print(
                f"| {instrument.symbol} | {h1.date() if h1 else 'n/a'} | "
                f"{h4.date() if h4 else 'n/a'} | {mtt_str} |"
            )


if __name__ == "__main__":
    asyncio.run(main())
