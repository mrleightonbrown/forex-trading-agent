"""FX-40: exports one backtest run as a canonical JSON report (plus the
generated `reports/index.json` and `reports/dashboard_data.js` the
static viewer, `fta_dashboard_sketch.html`, reads.

Observability/reporting only -- see that file's own header for the
full list of non-goals. This script strictly composes ALREADY-TRUSTED,
UNMODIFIED machinery:

    load NATIVE candles (existing SqlAlchemyCandleRepository)
            v
    run existing backtest engine (run_backtest / run_backtest_incremental)
            v
    simulate_trades (existing, unmodified)
            v
    compute_metrics (existing, unmodified)
            v
    to_report_dict (FX-40's own pure serializer)
            v
    write report + update index + regenerate dashboard_data.js

Supports a small, explicit set of concrete strategies (NOT a general
plugin architecture, per this story's own scope) -- see `STRATEGIES`
below. Where an incremental engine is the existing recommended one for
a strategy (golden-parity-tested against its slow reference elsewhere
in this project), it's used; otherwise the slow reference runs
unmodified. `MultiTimeframeTrendStrategy` is handled as its own
explicit special case (it needs an H4 candle series too) rather than
forced into the other strategies' uniform shape.

Research candle retrieval always explicitly requests
`source=CandleSource.NATIVE` (never `source=None`, which means "any
provenance" -- FX-38H.1's own hardening applied here too).

Run:
    uv run python scripts/export_backtest_report.py \\
        --strategy ema_crossover_v1 \\
        --instrument EUR_USD \\
        --from 2024-01-01 \\
        --to 2025-12-31

    # Override defaults for a strategy that takes them:
    uv run python scripts/export_backtest_report.py \\
        --strategy close_channel_breakout_v1 \\
        --instrument USD_JPY \\
        --from 2016-09-19 \\
        --to 2026-09-19 \\
        --params '{"lookback": 30}'

Requires:
    - `docker compose up -d db` (research dataset already backfilled)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from forex_agent.domain.backtest import run_backtest
from forex_agent.domain.backtest_metrics import compute_metrics
from forex_agent.domain.backtest_report import report_filename, to_report_dict
from forex_agent.domain.candle import Candle
from forex_agent.domain.candle_source import CandleSource
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.incremental_strategy import run_backtest_incremental
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.strategies.close_channel_breakout import CloseChannelBreakoutStrategy
from forex_agent.domain.strategies.ema_crossover import EmaCrossoverStrategy
from forex_agent.domain.strategies.ema_crossover_incremental import (
    IncrementalEmaCrossoverStrategy,
)
from forex_agent.domain.strategies.ema_crossover_trend_regime_gated import (
    EmaCrossoverTrendRegimeGatedStrategy,
)
from forex_agent.domain.strategies.ema_crossover_trend_regime_gated_incremental import (
    IncrementalEmaCrossoverTrendRegimeGatedStrategy,
)
from forex_agent.domain.strategies.mean_reversion import MeanReversionStrategy
from forex_agent.domain.strategies.multi_timeframe_trend import MultiTimeframeTrendStrategy
from forex_agent.domain.strategies.multi_timeframe_trend_incremental import (
    IncrementalMultiTimeframeTrendStrategy,
)
from forex_agent.domain.strategies.time_series_momentum import TimeSeriesMomentumStrategy
from forex_agent.domain.strategies.volatility_expansion import VolatilityExpansionBreakoutStrategy
from forex_agent.domain.strategies.volatility_expansion_incremental import (
    IncrementalVolatilityExpansionBreakoutStrategy,
)
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trade_simulation import simulate_trades
from forex_agent.infrastructure.db.candle_repository import SqlAlchemyCandleRepository
from forex_agent.infrastructure.db.session import get_engine

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"


@dataclass(frozen=True)
class StrategySpec:
    key: str
    default_parameters: dict[str, int | str | Decimal]
    slow_factory: Callable[..., Any]
    incremental_factory: Callable[..., Any] | None
    needs_h4: bool = False


STRATEGIES: dict[str, StrategySpec] = {
    "ema_crossover_v1": StrategySpec(
        key="ema_crossover_v1",
        default_parameters={"fast_period": 20, "slow_period": 50},
        slow_factory=EmaCrossoverStrategy,
        incremental_factory=IncrementalEmaCrossoverStrategy,
    ),
    "ema_crossover_trend_regime_gated_v1": StrategySpec(
        key="ema_crossover_trend_regime_gated_v1",
        default_parameters={
            "fast_period": 20,
            "slow_period": 50,
            "regime_period": 14,
            "regime_threshold": Decimal("25"),
        },
        slow_factory=EmaCrossoverTrendRegimeGatedStrategy,
        incremental_factory=IncrementalEmaCrossoverTrendRegimeGatedStrategy,
    ),
    "close_channel_breakout_v1": StrategySpec(
        key="close_channel_breakout_v1",
        default_parameters={"lookback": 20},
        slow_factory=CloseChannelBreakoutStrategy,
        incremental_factory=None,
    ),
    "volatility_expansion_breakout_v1": StrategySpec(
        key="volatility_expansion_breakout_v1",
        default_parameters={
            "short_period": 14,
            "long_period": 50,
            "breakout_lookback": 20,
            "expansion_threshold": Decimal("1.5"),
        },
        slow_factory=VolatilityExpansionBreakoutStrategy,
        incremental_factory=IncrementalVolatilityExpansionBreakoutStrategy,
    ),
    "mean_reversion_v1": StrategySpec(
        key="mean_reversion_v1",
        default_parameters={"period": 20, "entry_threshold": Decimal("2.0")},
        slow_factory=MeanReversionStrategy,
        incremental_factory=None,
    ),
    "time_series_momentum_v1": StrategySpec(
        key="time_series_momentum_v1",
        default_parameters={"lookback": 20, "threshold": Decimal("0")},
        slow_factory=TimeSeriesMomentumStrategy,
        incremental_factory=None,
    ),
    "multi_timeframe_trend_v1": StrategySpec(
        key="multi_timeframe_trend_v1",
        default_parameters={
            "h1_fast_period": 20,
            "h1_slow_period": 50,
            "h4_fast_period": 20,
            "h4_slow_period": 50,
        },
        slow_factory=MultiTimeframeTrendStrategy,
        incremental_factory=IncrementalMultiTimeframeTrendStrategy,
        needs_h4=True,
    ),
}


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", required=True, choices=sorted(STRATEGIES))
    parser.add_argument("--instrument", required=True, help="e.g. EUR_USD, USD_JPY, XAU_USD")
    parser.add_argument("--granularity", default="H1", choices=[g.value for g in Granularity])
    parser.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD")
    parser.add_argument("--to", dest="date_to", required=True, help="YYYY-MM-DD")
    parser.add_argument(
        "--params", default="{}", help="JSON object overriding the strategy's own defaults"
    )
    return parser.parse_args(argv)


def _parse_instrument(symbol: str) -> Instrument:
    base, _, quote = symbol.partition("_")
    if not base or not quote:
        raise SystemExit(f"--instrument must look like EUR_USD, got {symbol!r}")
    return Instrument(base_currency=base, quote_currency=quote)


def _parse_date(value: str) -> UtcTimestamp:
    return UtcTimestamp(datetime.fromisoformat(value).replace(tzinfo=UTC))


def _resolve_parameters(
    spec: StrategySpec, overrides_json: str
) -> tuple[dict[str, int | str | Decimal], bool]:
    """Merges CLI `--params` (a JSON object) over the strategy's own
    defaults. Returns `(parameters, is_default_configuration)` --
    Decimal-typed defaults (e.g. `regime_threshold`) are matched against
    a JSON override by comparing `Decimal(str(override))`, so a CLI
    override of `"25"` for a default of `Decimal("25")` still counts as
    "the default", not a spurious non-default filename suffix.
    """
    overrides = json.loads(overrides_json)
    if not isinstance(overrides, dict):
        raise SystemExit("--params must be a JSON object, e.g. '{\"fast_period\": 10}'")

    parameters: dict[str, int | str | Decimal] = dict(spec.default_parameters)
    is_default = True
    for key, value in overrides.items():
        if key not in spec.default_parameters:
            raise SystemExit(f"unknown parameter {key!r} for strategy {spec.key!r}")
        default = spec.default_parameters[key]
        if isinstance(default, Decimal):
            value = Decimal(str(value))
        parameters[key] = value
        if value != default:
            is_default = False
    return parameters, is_default


async def _load_candles(
    repo: SqlAlchemyCandleRepository,
    instrument: Instrument,
    granularity: Granularity,
    start: UtcTimestamp,
    end: UtcTimestamp,
) -> list[Candle]:
    return await repo.get_range(instrument, granularity, start, end, source=CandleSource.NATIVE)


async def _run_strategy(
    spec: StrategySpec,
    parameters: dict[str, int | str | Decimal],
    repo: SqlAlchemyCandleRepository,
    instrument: Instrument,
    granularity: Granularity,
    start: UtcTimestamp,
    end: UtcTimestamp,
) -> tuple[list[Candle], list[Any], Any]:
    """Returns `(h1_candles, hypotheses, strategy_instance)` -- the
    instance is returned too so the caller can read its own
    `strategy_key`/`strategy_version` directly (existing metadata,
    not a second model) rather than constructing a throwaway instance
    just to peek at them."""
    h1_candles = await _load_candles(repo, instrument, granularity, start, end)

    extra_kwargs: dict[str, Any] = {}
    if spec.needs_h4:
        h4_candles = await _load_candles(repo, instrument, Granularity.H4, start, end)
        extra_kwargs["h4_candles"] = h4_candles

    if spec.incremental_factory is not None:
        strategy = spec.incremental_factory(**extra_kwargs, **parameters)
        hypotheses = run_backtest_incremental(strategy, h1_candles)
    else:
        strategy = spec.slow_factory(**extra_kwargs, **parameters)
        hypotheses = run_backtest(strategy, h1_candles)
    return h1_candles, hypotheses, strategy


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
    except Exception:
        return "unknown"


def _write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n")
    tmp.replace(path)


def _update_index(reports_dir: Path, filename: str) -> None:
    index_path = reports_dir / "index.json"
    if index_path.exists():
        index = json.loads(index_path.read_text())
    else:
        index = {"schema_version": 1, "reports": []}
    reports = index.get("reports", [])
    if filename not in reports:
        reports.append(filename)
    index["reports"] = sorted(set(reports))
    _write_json_atomic(index_path, index)


def _regenerate_dashboard_data(reports_dir: Path) -> None:
    index_path = reports_dir / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {"reports": []}
    runs = []
    for filename in index.get("reports", []):
        report_path = reports_dir / filename
        if report_path.exists():
            runs.append(json.loads(report_path.read_text()))
    js_path = reports_dir / "dashboard_data.js"
    payload = json.dumps(runs, indent=2)
    js_path.write_text(f"window.FTA_BACKTEST_RUNS = {payload};\n")


async def main(argv: list[str]) -> None:
    args = _parse_args(argv)
    spec = STRATEGIES[args.strategy]
    instrument = _parse_instrument(args.instrument)
    granularity = Granularity(args.granularity)
    start = _parse_date(args.date_from)
    end = _parse_date(args.date_to)
    parameters, is_default = _resolve_parameters(spec, args.params)

    session_factory = async_sessionmaker(bind=get_engine())
    async with session_factory() as session:
        repo = SqlAlchemyCandleRepository(session)
        h1_candles, hypotheses, strategy = await _run_strategy(
            spec, parameters, repo, instrument, granularity, start, end
        )

    trades = simulate_trades(hypotheses, h1_candles)
    metrics = compute_metrics(trades) if trades else None

    report = to_report_dict(
        strategy_key=strategy.strategy_key,
        strategy_version=strategy.strategy_version,
        strategy_parameters=parameters,
        instrument=instrument,
        granularity=granularity,
        source=CandleSource.NATIVE,
        requested_start=start,
        requested_end=end,
        git_commit=_git_commit(),
        trades=trades,
        metrics=metrics,
        generated_at=UtcTimestamp(datetime.now(UTC)),
    )

    filename = report_filename(
        strategy_key=spec.key,
        instrument=instrument,
        granularity=granularity,
        requested_start=start,
        requested_end=end,
        strategy_parameters=parameters,
        is_default_configuration=is_default,
    )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(REPORTS_DIR / filename, report)
    _update_index(REPORTS_DIR, filename)
    _regenerate_dashboard_data(REPORTS_DIR)

    print(f"Wrote {REPORTS_DIR / filename}")
    print(f"  {len(trades)} trades, PF={report['metrics']['profit_factor']}")  # type: ignore[index]
    print(f"Updated {REPORTS_DIR / 'index.json'} and {REPORTS_DIR / 'dashboard_data.js'}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main(sys.argv[1:]))
