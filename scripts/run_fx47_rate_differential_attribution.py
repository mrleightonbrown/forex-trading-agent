"""FX-47: ATTRIBUTION of the existing policy-rate differential feature
(FX-42-FX-46H) against trades TWO EXISTING, already-committed strategies
generate UNCONDITIONALLY -- `MultiTimeframeTrendStrategy` (the literal
"H1/H4 trend trade" pattern) and `CloseChannelBreakoutStrategy` -- on the
three pairs with real differential coverage (EUR/USD, GBP/USD, USD/CAD;
USD/JPY, the pair these two candidates were originally holdout-tested on
in FX-38/39, has zero ingested policy-rate data, FX-42H.1's provider
mapping left deliberately unresolved, so it is out of scope here).

This is NOT a new strategy and NOT a filtered/gated strategy. No
strategy parameter is changed from what is already committed
(`MultiTimeframeTrendStrategy`'s and `CloseChannelBreakoutStrategy`'s
own defaults). No trade is suppressed, delayed, or resized based on the
differential. Every trade the strategy would generate on the FULL
available native-candle history is kept and simply bucketed, after the
fact, by two independent axes read through FX-46's own single seam
(`research.policy_rate_differential_research.evaluate_feature` ->
`ComputePolicyRateDifferential`) -- exactly the same "observe the
interaction before building anything conditional on it" shape as
FX-21/FX-21H's own `domain.regime_segmentation.segment_trades_by_regime`
(entry-regime attribution, not regime-gating), only later followed by an
actual gated strategy (FX-28) once an interaction was observed. FX-47 is
the FX-21 stage.

Two axes, reported SEPARATELY, never combined into one bucket:
  LEVEL: does the differential's sign at the trade's own entry time
    SUPPORT or OPPOSE the trade's own direction, or is it NEUTRAL (zero)?
  CHANGE: was the differential INCREASED, DECREASED, or UNCHANGED on the
    D-bar governing the trade's entry (FX-46's own per-day change
    classification, reused unmodified)?

Both axes are evaluated separately for ANNOUNCED and EFFECTIVE
semantics -- never pooled, never one falling back to the other, same
discipline as FX-46.

If no interaction appears in any bucket, that is reported as the
finding -- this script's own protocol forbids treating a null result as
a reason to try a different strategy, parameter, or bucketing scheme.

Run:
    uv run python scripts/run_fx47_rate_differential_attribution.py

Requires:
    - `docker compose up -d db`, `uv run alembic upgrade head`
    - the real policy-rate backfill (FX-43/44/45/46) and D-candle
      aggregation (`scripts/aggregate_d_candles.py`, FX-46) already run
    - native H1/H4 candles already ingested for EUR/USD, GBP/USD,
      USD/CAD (this project's base data ingestion, unrelated to this
      story)

Writes:
    - research_results/fx47/rate_differential_attribution.json
    - research_results/fx47/rate_differential_attribution_trades.csv
    - research_results/fx47/rate_differential_attribution_summary.md
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import subprocess
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from forex_agent.application.ports.macro_observation_repository import (
    MacroObservationRepository,
    VintageWriteOutcome,
)
from forex_agent.application.use_cases.compute_policy_rate_differential import (
    ComputePolicyRateDifferential,
)
from forex_agent.domain.backtest_metrics import BacktestMetrics, compute_metrics
from forex_agent.domain.block_bootstrap import (
    BlockLengthSelection,
    BootstrapResult,
    moving_block_bootstrap_means,
    select_block_length,
    summarize_bootstrap,
)
from forex_agent.domain.candle_source import CandleSource
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.incremental_strategy import run_backtest_incremental
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.macro_observation_vintage import MacroObservationVintage
from forex_agent.domain.policy_rate_differential import RateSemantics
from forex_agent.domain.release_timing_rule import ReleaseTimingConfidence
from forex_agent.domain.simulated_trade import SimulatedTrade
from forex_agent.domain.strategies.close_channel_breakout_incremental import (
    IncrementalCloseChannelBreakoutStrategy,
)
from forex_agent.domain.strategies.multi_timeframe_trend_incremental import (
    IncrementalMultiTimeframeTrendStrategy,
)
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trade_simulation import simulate_trades
from forex_agent.infrastructure.db.candle_repository import SqlAlchemyCandleRepository
from forex_agent.infrastructure.db.macro_observation_repository import (
    SqlAlchemyMacroObservationRepository,
)
from forex_agent.infrastructure.db.session import get_engine
from forex_agent.research.policy_rate_differential_research import (
    ERAS,
    FeatureEvaluation,
    assign_era,
    build_change_events,
    evaluate_feature,
)
from forex_agent.research.rate_differential_attribution import (
    TradeAttribution,
    attribute_trades,
    change_bucket_label,
    level_bucket_label,
)

PAIRS: tuple[Instrument, ...] = (
    Instrument(base_currency="EUR", quote_currency="USD"),
    Instrument(base_currency="GBP", quote_currency="USD"),
    Instrument(base_currency="USD", quote_currency="CAD"),
)
SEMANTICS: tuple[RateSemantics, ...] = (RateSemantics.ANNOUNCED, RateSemantics.EFFECTIVE)

#: This project's own FX-39/FX-46 bootstrap convention, reused
#: unchanged. Seed is this story's own number.
NUM_RESAMPLES = 10_000
SEED = 47
CONFIRM_LAGS = 3

#: Wide enough to comfortably bound every pair's real native-candle
#: history through the present; get_range's own [start, end) bounds do
#: the real clipping per pair.
_CANDLE_START = UtcTimestamp(datetime(2000, 1, 1, tzinfo=UTC))
_CANDLE_END = UtcTimestamp(datetime.now(UTC))

OUT_DIR = Path("research_results/fx47")


# --- Read-through cache over the real macro-observation repository ---------
# (identical in shape and justification to FX-46's own; see that script's
# own docstring -- copied rather than imported, matching this project's
# established "each research script is self-contained" convention.)


class _CachingMacroObservationRepository:
    def __init__(self, delegate: MacroObservationRepository) -> None:
        self._delegate = delegate
        self._cache: dict[str, tuple[MacroObservationVintage, ...]] = {}

    async def list_all_for_series(self, series_key: str) -> tuple[MacroObservationVintage, ...]:
        if series_key not in self._cache:
            self._cache[series_key] = await self._delegate.list_all_for_series(series_key)
        return self._cache[series_key]

    async def add_vintage(self, vintage: MacroObservationVintage) -> VintageWriteOutcome:
        return await self._delegate.add_vintage(vintage)

    async def replace_provisional_release_timing(
        self,
        series_key: str,
        observation_period: UtcTimestamp,
        revision_sequence: int,
        released_at: UtcTimestamp,
        effective_at: UtcTimestamp | None,
        confidence: ReleaseTimingConfidence,
    ) -> None:
        await self._delegate.replace_provisional_release_timing(
            series_key,
            observation_period,
            revision_sequence,
            released_at,
            effective_at,
            confidence,
        )

    async def correct_verified_release_timing(
        self,
        series_key: str,
        observation_period: UtcTimestamp,
        revision_sequence: int,
        expected_current_released_at: UtcTimestamp,
        expected_current_effective_at: UtcTimestamp | None,
        corrected_released_at: UtcTimestamp,
        corrected_effective_at: UtcTimestamp | None,
    ) -> None:
        await self._delegate.correct_verified_release_timing(
            series_key,
            observation_period,
            revision_sequence,
            expected_current_released_at,
            expected_current_effective_at,
            corrected_released_at,
            corrected_effective_at,
        )

    async def latest_available_as_of(
        self, series_key: str, as_of: UtcTimestamp
    ) -> MacroObservationVintage | None:
        return await self._delegate.latest_available_as_of(series_key, as_of)

    async def observation_as_known_at(
        self, series_key: str, observation_period: UtcTimestamp, as_of: UtcTimestamp
    ) -> MacroObservationVintage | None:
        return await self._delegate.observation_as_known_at(series_key, observation_period, as_of)


# --- Trade generation (existing strategies, unchanged parameters) ----------


async def _generate_trades(
    candle_repo: SqlAlchemyCandleRepository, instrument: Instrument
) -> dict[str, list[SimulatedTrade]]:
    h1_candles = await candle_repo.get_range(
        instrument, Granularity.H1, _CANDLE_START, _CANDLE_END, source=CandleSource.NATIVE
    )
    h4_candles = await candle_repo.get_range(
        instrument, Granularity.H4, _CANDLE_START, _CANDLE_END, source=CandleSource.NATIVE
    )

    ccb_hypotheses = run_backtest_incremental(IncrementalCloseChannelBreakoutStrategy(), h1_candles)
    ccb_trades = simulate_trades(ccb_hypotheses, h1_candles)

    mtt_hypotheses = run_backtest_incremental(
        IncrementalMultiTimeframeTrendStrategy(h4_candles=h4_candles), h1_candles
    )
    mtt_trades = simulate_trades(mtt_hypotheses, h1_candles)

    return {
        "CloseChannelBreakoutStrategy": ccb_trades,
        "MultiTimeframeTrendStrategy": mtt_trades,
    }


# --- Per-D-bar CHANGE precomputation (one per instrument x semantics) ------


async def _daily_evaluations(
    candle_repo: SqlAlchemyCandleRepository,
    use_case: ComputePolicyRateDifferential,
    instrument: Instrument,
    semantics: RateSemantics,
) -> list[FeatureEvaluation]:
    d_candles = await candle_repo.get_range(
        instrument, Granularity.D, _CANDLE_START, _CANDLE_END, source=CandleSource.AGGREGATED
    )
    return [
        await evaluate_feature(use_case, instrument, candle.start_time, semantics)
        for candle in d_candles
    ]


# --- Bucket statistics -------------------------------------------------------


def _era_breakdown(trades: list[SimulatedTrade]) -> dict[str, Any]:
    era_values: dict[str, list[Decimal]] = {label: [] for label, _, _ in ERAS}
    era_values["pre-2005"] = []
    for trade in trades:
        era = assign_era(trade.entry_time) or "pre-2005"
        era_values.setdefault(era, []).append(trade.pnl.amount)
    out: dict[str, Any] = {}
    for era, values in era_values.items():
        n = len(values)
        mean = (sum(values, Decimal(0)) / n) if n else None
        out[era] = {"count": n, "mean": str(mean) if mean is not None else None}
    return out


def _serialize_metrics(metrics: BacktestMetrics) -> dict[str, Any]:
    return {
        "trade_count": metrics.trade_count,
        "win_rate": str(metrics.win_rate),
        "expectancy": str(metrics.expectancy.amount),
        "profit_factor": str(metrics.profit_factor) if metrics.profit_factor is not None else None,
        "total_pnl": str(metrics.total_pnl.amount),
        "max_drawdown": str(metrics.max_drawdown.amount),
        "sharpe": str(metrics.sharpe) if metrics.sharpe is not None else None,
        "sortino": str(metrics.sortino) if metrics.sortino is not None else None,
    }


def _serialize_bootstrap(result: BootstrapResult) -> dict[str, Any]:
    return {k: str(v) for k, v in asdict(result).items()}


def _serialize_selection(selection: BlockLengthSelection) -> dict[str, Any]:
    d = asdict(selection)
    d["acf_by_lag"] = {str(k): str(v) for k, v in selection.acf_by_lag.items()}
    d["band"] = str(selection.band)
    return d


def _bucket_report(trades: list[SimulatedTrade]) -> dict[str, Any]:
    """Full stats for one bucket's trade list -- `compute_metrics`
    (FX-17), a moving-block bootstrap CI on expectancy (FX-39's own
    ACF-selected-block-length convention, seed=47), and an era-by-era
    breakdown (FX-46's own fixed `ERAS`). `None`/empty-shaped fields
    when `trades` is empty -- never a fabricated statistic for a bucket
    nobody's trades ever landed in."""
    if not trades:
        return {
            "metrics": None,
            "bootstrap": None,
            "block_length_selection": None,
            "era_breakdown": _era_breakdown(trades),
        }
    metrics = compute_metrics(trades)
    pnls = [t.pnl.amount for t in trades]
    n = len(pnls)
    max_lag = min(50, max(0, n // 4))
    max_block_length = max(1, n // 4)
    selection = select_block_length(
        pnls, max_lag=max_lag, confirm_lags=CONFIRM_LAGS, max_block_length=max_block_length
    )
    block_means = moving_block_bootstrap_means(
        pnls, block_length=selection.block_length, num_resamples=NUM_RESAMPLES, seed=SEED
    )
    bootstrap = summarize_bootstrap(pnls, block_means)
    return {
        "metrics": _serialize_metrics(metrics),
        "bootstrap": _serialize_bootstrap(bootstrap),
        "block_length_selection": _serialize_selection(selection),
        "era_breakdown": _era_breakdown(trades),
    }


def _axis_report(attributions: list[TradeAttribution], label_fn: Any, axis: str) -> dict[str, Any]:
    by_bucket: dict[str, list[SimulatedTrade]] = {}
    for a in attributions:
        label = label_fn(getattr(a, axis))
        by_bucket.setdefault(label, []).append(a.trade)
    return {label: _bucket_report(trades) for label, trades in sorted(by_bucket.items())}


# --- Output writers ----------------------------------------------------------

_CSV_FIELDS = [
    "strategy",
    "instrument",
    "semantics",
    "entry_time",
    "side",
    "pnl",
    "level_bucket",
    "change_bucket",
]


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".csv.tmp")
    with tmp_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    tmp_path.replace(path)


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2) + "\n")
    tmp_path.replace(path)


def _fmt(v: str | None) -> str:
    return v if v is not None else "n/a"


def _render_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# FX-47: Rate Differential x Existing Technical/Regime Evidence")
    lines.append("")
    lines.append(f"Generated: {report['generated_at']}  ")
    dirty = report.get("git_commit_dirty")
    dirty_suffix = " (clean)" if dirty is False else " (DIRTY)" if dirty else " (unknown)"
    lines.append(f"Git commit: {report['git_commit']}{dirty_suffix}")
    lines.append("")
    lines.append(
        "ATTRIBUTION only -- no strategy parameter was changed, no trade was gated, delayed, "
        "or resized based on the differential. Every trade the strategy generates on the full "
        "available history is bucketed after the fact by two independent axes, reported "
        "separately. A null result (no bucket differs meaningfully) is a valid, reported "
        "finding, not a reason to try a different bucketing scheme."
    )
    lines.append("")

    for instrument_symbol, by_strategy in report["results"].items():
        lines.append(f"## {instrument_symbol}")
        for strategy_label, by_semantics in by_strategy.items():
            for semantics_value, axes in by_semantics.items():
                lines.append("")
                lines.append(f"### {strategy_label} / {semantics_value}")
                for axis_name in ("level", "change"):
                    lines.append("")
                    lines.append(f"**{axis_name.upper()} axis**")
                    lines.append("")
                    lines.append(
                        "| Bucket | n | expectancy | PF | max DD | 90% CI | 95% CI | frac<=0 |"
                    )
                    lines.append("|---|---|---|---|---|---|---|---|")
                    for bucket, cell in sorted(axes[axis_name].items()):
                        m = cell["metrics"]
                        b = cell["bootstrap"]
                        if m is None:
                            lines.append(f"| {bucket} | 0 | n/a | n/a | n/a | n/a | n/a | n/a |")
                            continue
                        ci90 = f"[{b['lower_90']}, {b['upper_90']}]"
                        ci95 = f"[{b['lower_95']}, {b['upper_95']}]"
                        lines.append(
                            f"| {bucket} | {m['trade_count']} | {m['expectancy']} | "
                            f"{_fmt(m['profit_factor'])} | {m['max_drawdown']} | {ci90} | "
                            f"{ci95} | {b['fraction_le_zero']} |"
                        )
        lines.append("")

    lines.append("## Limitations")
    lines.append("")
    lines.append(
        "- This is attribution, not a trading signal or filter -- a bucket's own trade count, "
        "expectancy, and CI describe the SAMPLE that landed in it, nothing about future "
        "performance.\n"
        "- Bootstraps drawn from a small number of trades in a bucket are not equivalent to "
        "many independent historical samples -- interpret CI width accordingly, next to each "
        "bucket's own `n`.\n"
        "- BLOCKED/UNAVAILABLE/NO_GOVERNING_DAY buckets reflect this project's own current "
        "data coverage limits (see FX-45/FX-45H/FX-46), not a property of the differential "
        "itself -- a CI excluding zero in one of these buckets describes the strategy's own "
        "unconditional performance during a data-unavailable period, not a rate-differential "
        "interaction.\n"
        "- No multiple-comparison correction is applied across the many buckets/axes/cells "
        "reported here (unlike FX-39's own Holm-Bonferroni treatment of a small, pre-registered "
        "candidate set) -- with this many 95% CIs computed, a handful excluding zero by chance "
        "alone, even under a true null, is expected. Treat any single bucket's CI exclusion as "
        "suggestive, not confirmatory -- especially for a small-n bucket.\n"
        "- No parameter, strategy, instrument, or bucketing-scheme change occurred after "
        "seeing any result above."
    )
    lines.append("")
    return "\n".join(lines)


# --- Main --------------------------------------------------------------------


async def main() -> None:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    results: dict[str, Any] = {}
    csv_rows: list[dict[str, Any]] = []

    async with session_factory() as session:
        candle_repo = SqlAlchemyCandleRepository(session)
        raw_repo = SqlAlchemyMacroObservationRepository(session)
        cached_repo = _CachingMacroObservationRepository(raw_repo)
        use_case = ComputePolicyRateDifferential(repository=cached_repo)

        for instrument in PAIRS:
            print(f"{instrument.symbol}: generating trades ...")
            trades_by_strategy = await _generate_trades(candle_repo, instrument)
            for label, trades in trades_by_strategy.items():
                print(f"  {label}: {len(trades)} trades")

            instrument_out: dict[str, Any] = {}
            for strategy_label, trades in trades_by_strategy.items():
                semantics_out: dict[str, Any] = {}
                for semantics in SEMANTICS:
                    print(f"  {strategy_label} / {semantics.value}: evaluating differential ...")
                    daily = await _daily_evaluations(candle_repo, use_case, instrument, semantics)
                    daily_sorted = sorted(daily, key=lambda e: e.as_of.value)
                    change_events = build_change_events(daily)
                    events_by_as_of = {e.as_of.value: e for e in change_events}

                    level_evals = [
                        await evaluate_feature(use_case, instrument, trade.entry_time, semantics)
                        for trade in trades
                    ]
                    attributions = attribute_trades(
                        trades, level_evals, daily_sorted, events_by_as_of
                    )

                    for a in attributions:
                        csv_rows.append(
                            {
                                "strategy": strategy_label,
                                "instrument": instrument.symbol,
                                "semantics": semantics.value,
                                "entry_time": a.trade.entry_time.value.isoformat(),
                                "side": a.trade.side.value,
                                "pnl": str(a.trade.pnl.amount),
                                "level_bucket": level_bucket_label(a.level),
                                "change_bucket": change_bucket_label(a.change),
                            }
                        )

                    semantics_out[semantics.value] = {
                        "level": _axis_report(attributions, level_bucket_label, "level"),
                        "change": _axis_report(attributions, change_bucket_label, "change"),
                    }
                instrument_out[strategy_label] = semantics_out
            results[instrument.symbol] = instrument_out

    try:
        commit_hash = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
    except Exception:
        commit_hash = "unknown"

    try:
        dirty_output = (
            subprocess.check_output(
                ["git", "status", "--porcelain", "--", "src/forex_agent", __file__]
            )
            .decode()
            .strip()
        )
        git_commit_dirty: bool | None = bool(dirty_output)
    except Exception:
        git_commit_dirty = None

    config = {
        "instruments": [i.symbol for i in PAIRS],
        "rate_semantics": [s.value for s in SEMANTICS],
        "strategies": ["CloseChannelBreakoutStrategy", "MultiTimeframeTrendStrategy"],
        "num_resamples": NUM_RESAMPLES,
        "seed": SEED,
        "bootstrap_method": "moving_block_bootstrap_means",
        "confidence_level": "0.90/0.95",
        "candle_start_bound": _CANDLE_START.value.isoformat(),
        "candle_end_bound": _CANDLE_END.value.isoformat(),
    }
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()

    report: dict[str, Any] = {
        "story": "FX-47",
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "git_commit": commit_hash,
        "git_commit_dirty": git_commit_dirty,
        "config_hash": config_hash,
        "config": config,
        "results": results,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(report, OUT_DIR / "rate_differential_attribution.json")
    _write_csv(csv_rows, OUT_DIR / "rate_differential_attribution_trades.csv")
    markdown = _render_markdown(report)
    tmp_md = OUT_DIR / "rate_differential_attribution_summary.md.tmp"
    tmp_md.write_text(markdown)
    tmp_md.replace(OUT_DIR / "rate_differential_attribution_summary.md")

    print(f"\nWrote {OUT_DIR / 'rate_differential_attribution.json'}")
    print(f"Wrote {OUT_DIR / 'rate_differential_attribution_trades.csv'}")
    print(f"Wrote {OUT_DIR / 'rate_differential_attribution_summary.md'}")
    print(
        "\nNo strategy, parameter, or bucketing-scheme change occurs as a result of any "
        "outcome above -- this script's own protocol forbids it regardless of result."
    )


if __name__ == "__main__":
    asyncio.run(main())
