"""FX-38H (part 2): reruns FX-38's development/holdout comparison from
each series' `earliest_usable_research_candle` (not the raw
`earliest_available_candle`), using economically-sealed evaluation
windows (`domain.sealed_window_backtest`) instead of one continuous run
sliced by `entry_time` -- and audits FX-38's ORIGINAL continuous-run
methodology for boundary-straddling trades, showing their effect.

Strategy parameters are the same, unmodified defaults as FX-38 and
every story before it. `EARLIEST_USABLE_*` below is transcribed
verbatim from `determine_usable_history_start.py`'s own recorded
output (FX-38H part 1) -- not recomputed or re-guessed here.

This script IS the reproducible source of FX-38H's results: it writes
a machine-readable artifact (`research_results/fx38h/results.json`)
alongside the markdown tables it prints, so the numbers in
docs/DECISIONS.md are not markdown-only claims.

Run:
    uv run python scripts/run_fx38h_analysis.py

Requires:
    - `docker compose up -d db` (FX-38's extended research dataset
      already backfilled)
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from forex_agent.domain.backtest import run_backtest
from forex_agent.domain.backtest_metrics import BacktestMetrics, compute_metrics
from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.incremental_strategy import run_backtest_incremental
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.sealed_window_backtest import run_sealed_window_backtest
from forex_agent.domain.simulated_trade import SimulatedTrade
from forex_agent.domain.strategies.close_channel_breakout import CloseChannelBreakoutStrategy
from forex_agent.domain.strategies.ema_crossover_incremental import (
    IncrementalEmaCrossoverStrategy,
)
from forex_agent.domain.strategies.ema_crossover_trend_regime_gated_incremental import (
    IncrementalEmaCrossoverTrendRegimeGatedStrategy,
)
from forex_agent.domain.strategies.multi_timeframe_trend_incremental import (
    IncrementalMultiTimeframeTrendStrategy,
)
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trade_side import TradeSide
from forex_agent.domain.trade_simulation import simulate_trades
from forex_agent.infrastructure.db.candle_repository import SqlAlchemyCandleRepository
from forex_agent.infrastructure.db.session import get_engine

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")
GBP_USD = Instrument(base_currency="GBP", quote_currency="USD")
USD_JPY = Instrument(base_currency="USD", quote_currency="JPY")
USD_CAD = Instrument(base_currency="USD", quote_currency="CAD")
XAU_USD = Instrument(base_currency="XAU", quote_currency="USD")
INSTRUMENTS = [EUR_USD, GBP_USD, USD_JPY, USD_CAD, XAU_USD]

# --- Locked config (transcribed from FX-38H part 1's own output) ----------
WARMUP_DAYS = 60  # comfortably exceeds every locked strategy's longest period (50)
DEV_START = datetime(2016, 9, 19, tzinfo=UTC)
DEV_END = datetime(2026, 9, 20, tzinfo=UTC)  # matches FX-38's own "now" cutoff
# For the boundary-straddling audit only (criterion 9): a bounded window
# around FX-38's original 2016-09-19 boundary, not the full 24-year
# history -- 400 days each side comfortably exceeds every observed
# holding period across this whole project's own trade tables (at most a
# few weeks), so no real straddling trade could fall outside it.
STRADDLE_AUDIT_MARGIN_DAYS = 400

EARLIEST_USABLE_H1 = {
    EUR_USD: datetime(2005, 1, 20, tzinfo=UTC),
    GBP_USD: datetime(2005, 1, 20, tzinfo=UTC),
    USD_JPY: datetime(2005, 1, 20, tzinfo=UTC),
    USD_CAD: datetime(2005, 1, 21, tzinfo=UTC),
    XAU_USD: datetime(2006, 3, 19, tzinfo=UTC),
}
EARLIEST_USABLE_H4 = {
    EUR_USD: datetime(2005, 1, 21, tzinfo=UTC),
    GBP_USD: datetime(2005, 1, 21, tzinfo=UTC),
    USD_JPY: datetime(2005, 1, 21, tzinfo=UTC),
    USD_CAD: datetime(2005, 1, 22, tzinfo=UTC),
    XAU_USD: datetime(2006, 3, 19, tzinfo=UTC),
}
EARLIEST_USABLE_MTT = {i: max(EARLIEST_USABLE_H1[i], EARLIEST_USABLE_H4[i]) for i in INSTRUMENTS}

RESULTS: list[dict[str, Any]] = []
STRADDLE_AUDIT: list[dict[str, Any]] = []


def _d(x: Decimal | None) -> str | None:
    return str(x) if x is not None else None


async def _window_candles(
    repo: SqlAlchemyCandleRepository,
    instrument: Instrument,
    granularity: Granularity,
    window_start: datetime,
    window_end: datetime,
    warmup_days: int = WARMUP_DAYS,
) -> tuple[list[Candle], list[Candle]]:
    warmup_start = window_start - timedelta(days=warmup_days)
    all_candles = await repo.get_range(
        instrument, granularity, UtcTimestamp(warmup_start), UtcTimestamp(window_end), source=None
    )
    warmup = [c for c in all_candles if c.start_time.value < window_start]
    window = [c for c in all_candles if c.start_time.value >= window_start]
    return warmup, window


def _record_result(
    strategy_key: str,
    instrument: Instrument,
    period: str,
    window_start: datetime,
    window_end: datetime,
    candle_count: int,
    trades: list[SimulatedTrade],
) -> None:
    entry: dict[str, Any] = {
        "strategy": strategy_key,
        "instrument": instrument.symbol,
        "period": period,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "candle_count": candle_count,
        "trade_count": len(trades),
    }
    if trades:
        m: BacktestMetrics = compute_metrics(trades)
        longs = sum(1 for t in trades if t.side is TradeSide.LONG)
        shorts = sum(1 for t in trades if t.side is TradeSide.SHORT)
        entry.update(
            {
                "long_count": longs,
                "short_count": shorts,
                "win_count": m.win_count,
                "loss_count": m.loss_count,
                "win_rate": _d(m.win_rate),
                "average_win": _d(m.average_win.amount if m.average_win else None),
                "average_loss": _d(m.average_loss.amount if m.average_loss else None),
                "expectancy": _d(m.expectancy.amount),
                "currency": instrument.quote_currency,
                "profit_factor": _d(m.profit_factor),
                "total_pnl": _d(m.total_pnl.amount),
                "max_drawdown": _d(m.max_drawdown.amount),
                "sharpe": _d(m.sharpe),
                "sortino": _d(m.sortino),
            }
        )
        pf = f"{m.profit_factor:.3f}" if m.profit_factor is not None else "n/a"
        print(
            f"| {instrument.symbol} | {period} | {len(trades)} | {longs}/{shorts} | "
            f"{m.win_rate:.3f} | {_d(m.expectancy.amount)} {instrument.quote_currency} | {pf} |"
        )
    else:
        print(f"| {instrument.symbol} | {period} | 0 | - | - | - | n/a |")
    RESULTS.append(entry)


async def _run_sealed_strategy(
    repo: SqlAlchemyCandleRepository,
    strategy_key: str,
    make_run: Any,  # Callable[[Instrument], Callable[[list[Candle]], list]]
) -> None:
    print(f"\n## {strategy_key}\n")
    print("| Instrument | Period | n | L/S | Win% | Expectancy | PF |")
    print("|---|---|---|---|---|---|---|")
    for instrument in INSTRUMENTS:
        holdout_start = EARLIEST_USABLE_H1[instrument]
        for period, window_start, window_end in [
            ("holdout", holdout_start, DEV_START),
            ("development", DEV_START, DEV_END),
        ]:
            warmup, window = await _window_candles(
                repo, instrument, Granularity.H1, window_start, window_end
            )
            sealed = run_sealed_window_backtest(make_run(instrument), warmup, window)
            trades = simulate_trades(sealed, window)
            _record_result(
                strategy_key, instrument, period, window_start, window_end, len(window), trades
            )


async def _run_sealed_mtt(repo: SqlAlchemyCandleRepository) -> None:
    strategy_key = "multi_timeframe_trend_v1"
    print(f"\n## {strategy_key}\n")
    print("| Instrument | Period | n | L/S | Win% | Expectancy | PF |")
    print("|---|---|---|---|---|---|---|")
    for instrument in INSTRUMENTS:
        holdout_start = EARLIEST_USABLE_MTT[instrument]
        for period, window_start, window_end in [
            ("holdout", holdout_start, DEV_START),
            ("development", DEV_START, DEV_END),
        ]:
            warmup, window = await _window_candles(
                repo, instrument, Granularity.H1, window_start, window_end
            )
            # Anchored to THIS window's own start (holdout or development),
            # not EARLIEST_USABLE_H4 unconditionally -- for the development
            # window that would otherwise reach back to ~2002/2006 for no
            # reason, defeating the whole point of a bounded warm-up buffer.
            h4_start = window_start - timedelta(days=WARMUP_DAYS)
            h4_candles = await repo.get_range(
                instrument,
                Granularity.H4,
                UtcTimestamp(h4_start),
                UtcTimestamp(window_end),
                source=None,
            )

            def _run(candles: list[Candle], h4: list[Candle] = h4_candles) -> list:
                strategy = IncrementalMultiTimeframeTrendStrategy(h4_candles=h4)
                return run_backtest_incremental(strategy, candles)

            sealed = run_sealed_window_backtest(_run, warmup, window)
            trades = simulate_trades(sealed, window)
            _record_result(
                strategy_key, instrument, period, window_start, window_end, len(window), trades
            )


async def _run_sealed_ccb(repo: SqlAlchemyCandleRepository) -> None:
    strategy_key = "close_channel_breakout_v1"
    print(f"\n## {strategy_key}\n")
    print("| Instrument | Period | n | L/S | Win% | Expectancy | PF |")
    print("|---|---|---|---|---|---|---|")
    for instrument in INSTRUMENTS:
        holdout_start = EARLIEST_USABLE_H1[instrument]
        for period, window_start, window_end in [
            ("holdout", holdout_start, DEV_START),
            ("development", DEV_START, DEV_END),
        ]:
            warmup, window = await _window_candles(
                repo, instrument, Granularity.H1, window_start, window_end
            )
            t0 = time.time()
            sealed = run_sealed_window_backtest(
                lambda c: run_backtest(CloseChannelBreakoutStrategy(), c), warmup, window
            )
            trades = simulate_trades(sealed, window)
            elapsed = time.time() - t0
            _record_result(
                strategy_key, instrument, period, window_start, window_end, len(window), trades
            )
            print(f"<!-- {instrument.symbol}/{period}: {elapsed:.1f}s -->")


# --- Part: boundary-straddling audit of FX-38's ORIGINAL methodology ------


async def _audit_boundary_straddling(repo: SqlAlchemyCandleRepository) -> None:
    print("\n## Boundary-straddling audit (FX-38's original methodology)\n")
    boundary = DEV_START
    audit_start = boundary - timedelta(days=STRADDLE_AUDIT_MARGIN_DAYS)
    audit_end = boundary + timedelta(days=STRADDLE_AUDIT_MARGIN_DAYS)

    # EMA + gated EMA share this shape (incremental, no extra constructor
    # args); MultiTimeframeTrendStrategy and CloseChannelBreakoutStrategy
    # are handled separately below (different constructor / slow engine).
    incremental_strategies: list[tuple[str, Any]] = [
        ("ema_crossover_v1", lambda: IncrementalEmaCrossoverStrategy()),
        (
            "ema_crossover_trend_regime_gated_v1",
            lambda: IncrementalEmaCrossoverTrendRegimeGatedStrategy(),
        ),
    ]

    header = (
        "| Strategy | Instrument | Straddling trades | Original PF (audit window) | "
        "PF excluding straddlers |"
    )
    print(header)
    print("|---|---|---|---|---|")

    for instrument in INSTRUMENTS:
        audit_candles = await repo.get_range(
            instrument,
            Granularity.H1,
            UtcTimestamp(audit_start),
            UtcTimestamp(audit_end),
            source=None,
        )
        if not audit_candles:
            continue

        # EMA + gated EMA: incremental, cheap, continuous over the audit window
        for strategy_key, factory in incremental_strategies:
            strategy = factory()
            hyps = run_backtest_incremental(strategy, audit_candles)
            trades = simulate_trades(hyps, audit_candles)
            _report_straddlers(strategy_key, instrument, trades, boundary)

        # MultiTimeframeTrendStrategy: needs H4 too
        h4_candles = await repo.get_range(
            instrument,
            Granularity.H4,
            UtcTimestamp(audit_start),
            UtcTimestamp(audit_end),
            source=None,
        )
        mtt = IncrementalMultiTimeframeTrendStrategy(h4_candles=h4_candles)
        hyps = run_backtest_incremental(mtt, audit_candles)
        trades = simulate_trades(hyps, audit_candles)
        _report_straddlers("multi_timeframe_trend_v1", instrument, trades, boundary)

        # CloseChannelBreakoutStrategy: slow engine, still cheap at audit-window scale
        ccb = CloseChannelBreakoutStrategy()
        hyps = run_backtest(ccb, audit_candles)
        trades = simulate_trades(hyps, audit_candles)
        _report_straddlers("close_channel_breakout_v1", instrument, trades, boundary)


def _report_straddlers(
    strategy_key: str, instrument: Instrument, trades: list[SimulatedTrade], boundary: datetime
) -> None:
    straddlers = [t for t in trades if t.entry_time.value < boundary <= t.exit_time.value]
    if not trades:
        return
    original_metrics = compute_metrics(trades)
    remaining = [t for t in trades if t not in straddlers]
    excl_pf = compute_metrics(remaining).profit_factor if remaining else None

    original_pf_str = (
        f"{original_metrics.profit_factor:.3f}"
        if original_metrics.profit_factor is not None
        else "n/a"
    )
    excl_pf_str = f"{excl_pf:.3f}" if excl_pf is not None else "n/a"
    print(
        f"| {strategy_key} | {instrument.symbol} | {len(straddlers)} | "
        f"{original_pf_str} | {excl_pf_str} |"
    )

    STRADDLE_AUDIT.append(
        {
            "strategy": strategy_key,
            "instrument": instrument.symbol,
            "audit_window_trade_count": len(trades),
            "straddling_trade_count": len(straddlers),
            "straddling_trades": [
                {
                    "side": t.side.value,
                    "entry_time": t.entry_time.value.isoformat(),
                    "entry_price": str(t.entry_price),
                    "exit_time": t.exit_time.value.isoformat(),
                    "exit_price": str(t.exit_price),
                    "pnl": str(t.pnl.amount),
                }
                for t in straddlers
            ],
            "audit_window_profit_factor": _d(original_metrics.profit_factor),
            "profit_factor_excluding_straddlers": _d(excl_pf),
        }
    )


async def main() -> None:
    session_factory = async_sessionmaker(bind=get_engine())
    async with session_factory() as session:
        repo = SqlAlchemyCandleRepository(session)

        await _run_sealed_strategy(
            repo,
            "ema_crossover_v1",
            lambda instrument: (
                lambda candles: run_backtest_incremental(IncrementalEmaCrossoverStrategy(), candles)
            ),
        )
        await _run_sealed_strategy(
            repo,
            "ema_crossover_trend_regime_gated_v1",
            lambda instrument: (
                lambda candles: run_backtest_incremental(
                    IncrementalEmaCrossoverTrendRegimeGatedStrategy(), candles
                )
            ),
        )
        await _run_sealed_mtt(repo)
        await _run_sealed_ccb(repo)
        await _audit_boundary_straddling(repo)

    try:
        commit_hash = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
    except Exception:
        commit_hash = "unknown"

    artifact = {
        "experiment": "FX-38H",
        "generated_at": datetime.now(UTC).isoformat(),
        "git_commit": commit_hash,
        "config": {
            "warmup_days": WARMUP_DAYS,
            "development_window": {"start": DEV_START.isoformat(), "end": DEV_END.isoformat()},
            "straddle_audit_margin_days": STRADDLE_AUDIT_MARGIN_DAYS,
            "usable_history_algorithm": {
                "window_days": 90,
                "coverage_threshold": "0.95",
                "sustained_windows": 8,
                "max_unexplained_gap_hours": 72,
            },
            "earliest_usable_h1": {k.symbol: v.isoformat() for k, v in EARLIEST_USABLE_H1.items()},
            "earliest_usable_h4": {k.symbol: v.isoformat() for k, v in EARLIEST_USABLE_H4.items()},
            "earliest_usable_mtt": {
                k.symbol: v.isoformat() for k, v in EARLIEST_USABLE_MTT.items()
            },
            "strategy_parameters": {
                "ema_crossover_v1": {"fast_period": 20, "slow_period": 50},
                "ema_crossover_trend_regime_gated_v1": {
                    "fast_period": 20,
                    "slow_period": 50,
                    "regime_period": 14,
                    "regime_threshold": "25",
                },
                "multi_timeframe_trend_v1": {
                    "h1_fast_period": 20,
                    "h1_slow_period": 50,
                    "h4_fast_period": 20,
                    "h4_slow_period": 50,
                },
                "close_channel_breakout_v1": {"lookback": 20},
            },
        },
        "results": RESULTS,
        "boundary_straddling_audit": STRADDLE_AUDIT,
    }

    out_dir = Path(__file__).resolve().parent.parent / "research_results" / "fx38h"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "results.json"
    out_path.write_text(json.dumps(artifact, indent=2, sort_keys=False))
    print(f"\nWrote machine-readable artifact: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
