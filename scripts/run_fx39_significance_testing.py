"""FX-39 (part 2): applies `domain.block_bootstrap` to the four FX-38H
holdout candidates -- the natural next question external review named:
are their ~1.05-1.18 holdout profit factors statistically
distinguishable from noise once trade dependence and regime clustering
are accounted for? -- plus two negative controls (comparison strategies
already known to sign-flip in the holdout) as a validation check on the
method itself: if the bootstrap can't distinguish an ALREADY-NEGATIVE
result from "noise" in the expected direction, that's a red flag on the
method, not the strategies.

Reuses FX-38H.1's own sealed-window methodology EXACTLY (same warm-up
bound, same `CandleSource.NATIVE` filtering, same locked default
strategy parameters) to regenerate the six (strategy, instrument)
holdout trade lists -- no strategy or parameter changes, and no change
to how those trades are produced. This script's own job starts only
after that: turning each trade list's P&L sequence into a bootstrap
significance test.

LOCKED PROTOCOL (before any real result was computed):

  Primary endpoint: mean per-trade expectancy.
  Primary inferential method: moving-block bootstrap (MBB).
  H0: expectancy <= 0.  H1: expectancy > 0.
  Bootstrap: 10,000 resamples, fixed published seed (39).
  Block length: objective ACF rule (`select_block_length`), capped at
    n // 4 so pathological ACF behavior can't select an absurd block;
    full ACF diagnostics recorded for every series, not just the
    selected length.
  Confidence: 90% and 95% percentile CIs.
  Interpretation tiers (mechanical, decided BEFORE any result):
    95% lower bound > 0            -> "evidence of positive expectancy"
    90% lower bound > 0, 95% not   -> "suggestive, not strong evidence"
    90% lower bound <= 0           -> "cannot distinguish from noise"
  Multiplicity: raw one-sided p-values reported AND Holm-adjusted
    across the FOUR candidates (not the two negative controls, which
    are not part of the "selected by prior research" multiplicity
    problem).
  Secondary robustness check: whole 2-year regime-block bootstrap.
    The number of source regime blocks (~5-6) is reported explicitly
    next to every regime CI -- 10,000 resamples from 5-6 blocks is NOT
    10,000 independent historical regimes, and this report never
    implies otherwise.
  Controls: USD_JPY + EmaCrossoverStrategy, XAU_USD +
    EmaCrossoverTrendRegimeGatedStrategy (both already known to
    sign-flip in the holdout).

  FORBIDDEN, unconditionally, regardless of outcome: parameter
  optimization, strategy modification, instrument substitution, period
  substitution, exclusion of unfavorable regimes, or post-result change
  of bootstrap method. If a candidate's result doesn't survive, that is
  the answer -- not a prompt to try a different breakout lookback or
  add a filter.

Writes a machine-readable artifact (`research_results/fx39/
results.json`, including every series' full ACF diagnostics) alongside
the markdown tables and classification matrix it prints.

Run:
    uv run python scripts/run_fx39_significance_testing.py

Requires:
    - `docker compose up -d db` (FX-38's extended research dataset
      already backfilled)
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from forex_agent.domain.backtest import run_backtest
from forex_agent.domain.backtest_metrics import compute_metrics
from forex_agent.domain.block_bootstrap import (
    BlockLengthSelection,
    BootstrapResult,
    holm_bonferroni_adjusted_p_values,
    moving_block_bootstrap_means,
    segment_block_bootstrap_means,
    select_block_length,
    summarize_bootstrap,
)
from forex_agent.domain.candle import Candle
from forex_agent.domain.candle_source import CandleSource
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
from forex_agent.domain.trade_simulation import simulate_trades
from forex_agent.infrastructure.db.candle_repository import SqlAlchemyCandleRepository
from forex_agent.infrastructure.db.session import get_engine

USD_JPY = Instrument(base_currency="USD", quote_currency="JPY")
XAU_USD = Instrument(base_currency="XAU", quote_currency="USD")

# --- Locked config, transcribed from FX-38H.1's own constants --------------
WARMUP_DAYS = 60
DEV_START = datetime(2016, 9, 19, tzinfo=UTC)
EARLIEST_USABLE_H1 = {
    USD_JPY: datetime(2005, 1, 20, tzinfo=UTC),
    XAU_USD: datetime(2006, 3, 19, tzinfo=UTC),
}
EARLIEST_USABLE_H4 = {
    USD_JPY: datetime(2005, 1, 21, tzinfo=UTC),
    XAU_USD: datetime(2006, 3, 19, tzinfo=UTC),
}
EARLIEST_USABLE_MTT = {
    i: max(EARLIEST_USABLE_H1[i], EARLIEST_USABLE_H4[i]) for i in (USD_JPY, XAU_USD)
}

# --- FX-39's own locked config (chosen before any real result) -------------
NUM_RESAMPLES = 10_000
SEED = 39
REGIME_BUCKET_YEARS = 2
CONFIRM_LAGS = 3

CANDIDATE_RESULTS: list[dict[str, Any]] = []
CONTROL_RESULTS: list[dict[str, Any]] = []


async def _window_candles(
    repo: SqlAlchemyCandleRepository,
    instrument: Instrument,
    granularity: Granularity,
    window_start: datetime,
    window_end: datetime,
    earliest_usable: datetime,
) -> tuple[list[Candle], list[Candle]]:
    warmup_start = max(window_start - timedelta(days=WARMUP_DAYS), earliest_usable)
    all_candles = await repo.get_range(
        instrument,
        granularity,
        UtcTimestamp(warmup_start),
        UtcTimestamp(window_end),
        source=CandleSource.NATIVE,
    )
    warmup = [c for c in all_candles if c.start_time.value < window_start]
    window = [c for c in all_candles if c.start_time.value >= window_start]
    return warmup, window


async def _holdout_trades_h1_only(
    repo: SqlAlchemyCandleRepository, instrument: Instrument, run: Any
) -> list[SimulatedTrade]:
    holdout_start = EARLIEST_USABLE_H1[instrument]
    warmup, window = await _window_candles(
        repo, instrument, Granularity.H1, holdout_start, DEV_START, holdout_start
    )
    sealed = run_sealed_window_backtest(run, warmup, window)
    return simulate_trades(sealed, window)


async def _holdout_trades_mtt(
    repo: SqlAlchemyCandleRepository, instrument: Instrument
) -> list[SimulatedTrade]:
    holdout_start = EARLIEST_USABLE_MTT[instrument]
    warmup, window = await _window_candles(
        repo, instrument, Granularity.H1, holdout_start, DEV_START, EARLIEST_USABLE_H1[instrument]
    )
    h4_start = max(holdout_start - timedelta(days=WARMUP_DAYS), EARLIEST_USABLE_H4[instrument])
    h4_candles = await repo.get_range(
        instrument,
        Granularity.H4,
        UtcTimestamp(h4_start),
        UtcTimestamp(DEV_START),
        source=CandleSource.NATIVE,
    )

    def _run(candles: list[Candle], h4: list[Candle] = h4_candles) -> list:
        strategy = IncrementalMultiTimeframeTrendStrategy(h4_candles=h4)
        return run_backtest_incremental(strategy, candles)

    sealed = run_sealed_window_backtest(_run, warmup, window)
    return simulate_trades(sealed, window)


def _regime_segments(trades: list[SimulatedTrade], holdout_start: datetime) -> list[list[Decimal]]:
    """2-year buckets over the holdout window's own span, freshly
    anchored here (not FX-38's original dev+holdout-spanning Part F
    buckets, which don't apply to this narrower usable-history holdout
    window) -- same 2-year granularity, purpose-built for this test."""
    segments: list[list[Decimal]] = []
    cursor = datetime(holdout_start.year, 1, 1, tzinfo=UTC)
    while cursor < DEV_START:
        bucket_end = datetime(cursor.year + REGIME_BUCKET_YEARS, 1, 1, tzinfo=UTC)
        segment = [t.pnl.amount for t in trades if cursor <= t.entry_time.value < bucket_end]
        if segment:
            segments.append(segment)
        cursor = bucket_end
    return segments


def _tier(result: BootstrapResult) -> str:
    if result.lower_95 > 0:
        return "evidence of positive expectancy"
    if result.lower_90 > 0:
        return "suggestive, not strong evidence"
    return "cannot distinguish from noise"


def _analyze(label: str, trades: list[SimulatedTrade], holdout_start: datetime) -> dict[str, Any]:
    pnls = [t.pnl.amount for t in trades]
    n = len(pnls)
    currency = trades[0].instrument.quote_currency
    metrics = compute_metrics(trades)

    max_lag = min(50, n // 4)
    max_block_length = max(1, n // 4)
    selection = select_block_length(
        pnls, max_lag=max_lag, confirm_lags=CONFIRM_LAGS, max_block_length=max_block_length
    )
    block_means = moving_block_bootstrap_means(
        pnls, block_length=selection.block_length, num_resamples=NUM_RESAMPLES, seed=SEED
    )
    mbb_result = summarize_bootstrap(pnls, block_means)

    segments = _regime_segments(trades, holdout_start)
    regime_means = segment_block_bootstrap_means(segments, num_resamples=NUM_RESAMPLES, seed=SEED)
    regime_result = summarize_bootstrap(pnls, regime_means)

    tier = _tier(mbb_result)
    regime_tier = _tier(regime_result)

    print(f"\n## {label}\n")
    pf = f"{metrics.profit_factor:.3f}" if metrics.profit_factor is not None else "n/a"
    print("| Metric | Value |")
    print("|---|---|")
    print(f"| Trades | {n} |")
    print(f"| Observed expectancy | {metrics.expectancy.amount:.5f} {currency} |")
    print(f"| Observed PF | {pf} |")
    print(
        f"| MBB block length | {selection.block_length} "
        f"(fallback={selection.used_fallback}, capped={selection.capped_by_max_block_length}) |"
    )
    print(f"| MBB bootstrap mean expectancy | {mbb_result.observed_mean:.5f} {currency} |")
    print(f"| MBB 90% CI | [{mbb_result.lower_90:.5f}, {mbb_result.upper_90:.5f}] |")
    print(f"| MBB 95% CI | [{mbb_result.lower_95:.5f}, {mbb_result.upper_95:.5f}] |")
    print(f"| MBB raw one-sided p (H0: expectancy<=0) | {mbb_result.fraction_le_zero:.4f} |")
    print(f"| P(expectancy > 0), MBB | {(1 - mbb_result.fraction_le_zero):.2%} |")
    print(f"| MBB interpretation tier | {tier} |")
    print(f"| Regime blocks available | {len(segments)} |")
    regime_ci_90 = f"[{regime_result.lower_90:.5f}, {regime_result.upper_90:.5f}]"
    regime_ci_95 = f"[{regime_result.lower_95:.5f}, {regime_result.upper_95:.5f}]"
    print(f"| Regime-bootstrap 90% CI | {regime_ci_90} |")
    print(f"| Regime-bootstrap 95% CI | {regime_ci_95} |")
    print(f"| Regime robustness tier | {regime_tier} |")

    return {
        "label": label,
        "n": n,
        "currency": currency,
        "observed_expectancy": str(metrics.expectancy.amount),
        "observed_profit_factor": str(metrics.profit_factor) if metrics.profit_factor else None,
        "block_length_selection": _serialize_selection(selection),
        "mbb": _serialize_bootstrap(mbb_result),
        "mbb_tier": tier,
        "regime_segment_count": len(segments),
        "regime_block": _serialize_bootstrap(regime_result),
        "regime_tier": regime_tier,
    }


def _serialize_selection(selection: BlockLengthSelection) -> dict[str, Any]:
    d = asdict(selection)
    d["acf_by_lag"] = {str(k): str(v) for k, v in selection.acf_by_lag.items()}
    d["band"] = str(selection.band)
    return d


def _serialize_bootstrap(result: BootstrapResult) -> dict[str, Any]:
    return {k: str(v) for k, v in asdict(result).items()}


async def main() -> None:
    session_factory = async_sessionmaker(bind=get_engine())
    async with session_factory() as session:
        repo = SqlAlchemyCandleRepository(session)

        print("### The four candidates\n")

        ccb_jpy = await _holdout_trades_h1_only(
            repo, USD_JPY, lambda c: run_backtest(CloseChannelBreakoutStrategy(), c)
        )
        CANDIDATE_RESULTS.append(
            _analyze(
                "USD_JPY + CloseChannelBreakoutStrategy (holdout)",
                ccb_jpy,
                EARLIEST_USABLE_H1[USD_JPY],
            )
        )

        mtt_jpy = await _holdout_trades_mtt(repo, USD_JPY)
        CANDIDATE_RESULTS.append(
            _analyze(
                "USD_JPY + MultiTimeframeTrendStrategy (holdout)",
                mtt_jpy,
                EARLIEST_USABLE_MTT[USD_JPY],
            )
        )

        ccb_xau = await _holdout_trades_h1_only(
            repo, XAU_USD, lambda c: run_backtest(CloseChannelBreakoutStrategy(), c)
        )
        CANDIDATE_RESULTS.append(
            _analyze(
                "XAU_USD + CloseChannelBreakoutStrategy (holdout)",
                ccb_xau,
                EARLIEST_USABLE_H1[XAU_USD],
            )
        )

        mtt_xau = await _holdout_trades_mtt(repo, XAU_USD)
        CANDIDATE_RESULTS.append(
            _analyze(
                "XAU_USD + MultiTimeframeTrendStrategy (holdout)",
                mtt_xau,
                EARLIEST_USABLE_MTT[XAU_USD],
            )
        )

        print("\n### Negative controls (already known to sign-flip in the holdout)\n")

        ema_jpy = await _holdout_trades_h1_only(
            repo, USD_JPY, lambda c: run_backtest_incremental(IncrementalEmaCrossoverStrategy(), c)
        )
        CONTROL_RESULTS.append(
            _analyze(
                "USD_JPY + EmaCrossoverStrategy (holdout, negative control)",
                ema_jpy,
                EARLIEST_USABLE_H1[USD_JPY],
            )
        )

        def _gated(c: list[Candle]) -> list:
            return run_backtest_incremental(IncrementalEmaCrossoverTrendRegimeGatedStrategy(), c)

        gated_xau = await _holdout_trades_h1_only(repo, XAU_USD, _gated)
        CONTROL_RESULTS.append(
            _analyze(
                "XAU_USD + EmaCrossoverTrendRegimeGatedStrategy (holdout, negative control)",
                gated_xau,
                EARLIEST_USABLE_H1[XAU_USD],
            )
        )

    # --- Multiple-comparison correction across the four candidates only ---
    raw_p = [Decimal(r["mbb"]["fraction_le_zero"]) for r in CANDIDATE_RESULTS]
    adjusted_p = holm_bonferroni_adjusted_p_values(raw_p)
    for result, p_adj in zip(CANDIDATE_RESULTS, adjusted_p, strict=True):
        result["holm_adjusted_p"] = str(p_adj)

    print("\n### Multiple-comparison correction (Holm, across the four candidates only)\n")
    print("| Candidate | Raw one-sided p | Holm-adjusted p |")
    print("|---|---|---|")
    for result, p_adj in zip(CANDIDATE_RESULTS, adjusted_p, strict=True):
        print(f"| {result['label']} | {result['mbb']['fraction_le_zero']} | {p_adj} |")

    # --- Classification matrix ---------------------------------------------
    print("\n### Classification matrix\n")
    print("| Candidate | MBB evidence (95% CI > 0) | Regime robustness (95% CI > 0) |")
    print("|---|---|---|")
    for result in CANDIDATE_RESULTS:
        mbb_yes = "yes" if result["mbb_tier"] == "evidence of positive expectancy" else "no"
        regime_yes = "yes" if result["regime_tier"] == "evidence of positive expectancy" else "no"
        print(f"| {result['label']} | {mbb_yes} | {regime_yes} |")

    print(
        "\nNo parameter, strategy, instrument, or period changes occur as a result of "
        "any outcome above -- this script's own protocol forbids it regardless of result."
    )

    try:
        commit_hash = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
    except Exception:
        commit_hash = "unknown"

    artifact = {
        "experiment": "FX-39",
        "generated_at": datetime.now(UTC).isoformat(),
        "git_commit": commit_hash,
        "config": {
            "num_resamples": NUM_RESAMPLES,
            "seed": SEED,
            "regime_bucket_years": REGIME_BUCKET_YEARS,
            "confirm_lags": CONFIRM_LAGS,
            "warmup_days": WARMUP_DAYS,
        },
        "candidates": CANDIDATE_RESULTS,
        "negative_controls": CONTROL_RESULTS,
    }
    out_dir = Path(__file__).resolve().parent.parent / "research_results" / "fx39"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "results.json"
    out_path.write_text(json.dumps(artifact, indent=2))
    print(f"\nWrote machine-readable artifact: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
