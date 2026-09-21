"""FX-40: pure serializer turning already-computed backtest results into
the canonical, on-disk report schema `scripts/export_backtest_report.py`
writes and `fta_dashboard_sketch.html` reads.

Deliberately a pure FORMATTER, not a use case or a port: performs no
file I/O, no database access, no network access, no metric
recomputation, no backtesting, and no trade simulation. It serializes
only the trusted `list[SimulatedTrade]` and `BacktestMetrics` a caller
already produced via the existing, unmodified `run_backtest`/
`run_backtest_incremental` + `simulate_trades` + `compute_metrics`
pipeline. `git_commit` and `generated_at` are supplied by the caller
(not computed here) for the same reason -- a subprocess call or a
`datetime.now()` read would make this function impure and untestable
with exact expected output.

Decimal rule (CLAUDE.md: never use float for prices/balances/P&L):
every `Decimal`-derived value -- prices, `Money` amounts, ratios like
win_rate/profit_factor/Sharpe/Sortino, and any `Decimal`-typed strategy
parameter -- serializes as a JSON string, never a JSON number. `Money`
serializes as just its `.amount` string, not `{amount, currency}`: the
report's own `instrument` field already fixes the currency (this
project's own invariant, enforced by `compute_metrics` itself, is that
every trade's `pnl.currency` equals the instrument's `quote_currency`),
so nothing is lost by not repeating it on every single money field.
Plain integers (trade/win/loss/breakeven counts, `int`-typed strategy
parameters) stay JSON integers. A mathematically undefined metric
(e.g. `profit_factor` with zero gross loss, or every metric when there
are zero trades) serializes as JSON `null` -- never a fabricated `0`,
`"None"`, or `"nan"`.
"""

import hashlib
import json
from decimal import Decimal
from typing import Any

from forex_agent.domain.backtest_metrics import BacktestMetrics
from forex_agent.domain.candle_source import CandleSource
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.simulated_trade import SimulatedTrade
from forex_agent.domain.timestamps import UtcTimestamp

SCHEMA_VERSION = 1


def to_report_dict(
    *,
    strategy_key: str,
    strategy_version: str,
    strategy_parameters: dict[str, int | str | Decimal],
    instrument: Instrument,
    granularity: Granularity,
    source: CandleSource,
    requested_start: UtcTimestamp,
    requested_end: UtcTimestamp,
    git_commit: str,
    trades: list[SimulatedTrade],
    metrics: BacktestMetrics | None,
    generated_at: UtcTimestamp,
) -> dict[str, Any]:
    """Builds the canonical report dict (JSON-serializable as-is via
    `json.dumps`, no custom encoder needed -- every value is already a
    `str`, `int`, `bool`, `None`, `list`, or `dict` of those).

    `metrics` is `None` exactly when `trades` is empty -- `compute_
    metrics` itself refuses an empty trade list (a report on zero
    trades is meaningful, computing statistics over zero trades isn't),
    so the caller passes `None` rather than inventing a placeholder
    `BacktestMetrics`; this function then reports every metric as `null`
    rather than fabricating zeros. If `trades` is non-empty, `metrics`
    must be provided (callers are expected to have run the existing,
    unmodified `compute_metrics` over exactly these `trades` first --
    this function does not check that they actually correspond, since
    doing so would require recomputation, which it is deliberately
    forbidden from doing).

    Raises `ValueError` if `trades` is empty but `metrics` is given (or
    vice versa) -- the two must agree on whether there were any trades,
    since `metrics is None` IS how this function represents "no trades"
    downstream.
    """
    if (not trades) != (metrics is None):
        raise ValueError(
            "trades and metrics must agree on emptiness: metrics is None iff trades is empty "
            f"(got {len(trades)} trades, metrics={'present' if metrics is not None else 'None'})"
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso_z(generated_at),
        "strategy": {
            "key": strategy_key,
            "version": strategy_version,
            "parameters": {k: _format_parameter(v) for k, v in strategy_parameters.items()},
        },
        "instrument": instrument.symbol,
        "granularity": granularity.value,
        "source": source.value,
        "from": _iso_z(requested_start),
        "to": _iso_z(requested_end),
        "git_commit": git_commit,
        "metrics": _metrics_dict(metrics),
        "trades": [_trade_dict(t) for t in trades],
    }


def _format_parameter(value: int | str | Decimal) -> int | str:
    """`Decimal` parameters (e.g. `expansion_threshold`) become strings;
    `int`/`str` parameters (e.g. `fast_period`, `lookback`) pass through
    unchanged -- they are genuinely integers/strings in the domain, not
    Decimals, so stringifying them would misrepresent the schema."""
    if isinstance(value, Decimal):
        return str(value)
    return value


def _trade_dict(trade: SimulatedTrade) -> dict[str, Any]:
    return {
        "side": trade.side.value,
        "entry_time": _iso_z(trade.entry_time),
        "entry_price": str(trade.entry_price),
        "exit_time": _iso_z(trade.exit_time),
        "exit_price": str(trade.exit_price),
        "pnl": str(trade.pnl.amount),
    }


def _metrics_dict(metrics: BacktestMetrics | None) -> dict[str, Any]:
    if metrics is None:
        return {
            "trade_count": 0,
            "win_count": 0,
            "loss_count": 0,
            "breakeven_count": 0,
            "win_rate": None,
            "average_win": None,
            "average_loss": None,
            "expectancy": None,
            "profit_factor": None,
            "total_pnl": None,
            "max_drawdown": None,
            "sharpe": None,
            "sortino": None,
        }
    return {
        "trade_count": metrics.trade_count,
        "win_count": metrics.win_count,
        "loss_count": metrics.loss_count,
        "breakeven_count": metrics.breakeven_count,
        "win_rate": str(metrics.win_rate),
        "average_win": str(metrics.average_win.amount) if metrics.average_win else None,
        "average_loss": str(metrics.average_loss.amount) if metrics.average_loss else None,
        "expectancy": str(metrics.expectancy.amount),
        "profit_factor": str(metrics.profit_factor) if metrics.profit_factor is not None else None,
        "total_pnl": str(metrics.total_pnl.amount),
        "max_drawdown": str(metrics.max_drawdown.amount),
        "sharpe": str(metrics.sharpe) if metrics.sharpe is not None else None,
        "sortino": str(metrics.sortino) if metrics.sortino is not None else None,
    }


def _iso_z(ts: UtcTimestamp) -> str:
    """UTC ISO-8601 with a literal `Z` suffix (`UtcTimestamp` already
    guarantees UTC, so `.isoformat()` always yields `+00:00` here --
    just swapped for the more common `Z` form)."""
    return ts.value.isoformat(timespec="seconds").replace("+00:00", "Z")


def config_identifier(strategy_parameters: dict[str, int | str | Decimal]) -> str:
    """A short, deterministic, PERSISTENT identifier for one specific
    parameter configuration: sha256 of a canonical (sorted-keys, no
    whitespace) JSON encoding of the (Decimal-safe-formatted)
    parameters, truncated to 8 hex characters.

    Deliberately NOT Python's built-in `hash()`: CPython randomizes
    `hash()` for `str` (and therefore most JSON-shaped structures) by a
    per-process salt (`PYTHONHASHSEED`) unless explicitly disabled --
    unusable as a persistent identifier that must mean the same thing
    across separate runs, processes, or machines. `sha256` has no such
    randomization.
    """
    canonical = json.dumps(
        {k: _format_parameter(v) for k, v in strategy_parameters.items()},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8]


def report_filename(
    *,
    strategy_key: str,
    instrument: Instrument,
    granularity: Granularity,
    requested_start: UtcTimestamp,
    requested_end: UtcTimestamp,
    strategy_parameters: dict[str, int | str | Decimal],
    is_default_configuration: bool,
) -> str:
    """A deterministic, readable filename for one report:
    `<strategy_key>_<INSTRUMENT>_<GRANULARITY>_<YYYYMMDD>_<YYYYMMDD>.json`
    for the common case (`is_default_configuration=True`, matching this
    story's own example), with an 8-character `config_identifier`
    suffix appended whenever `is_default_configuration=False` -- so a
    genuinely different parameter configuration for the same strategy/
    instrument/granularity/date-range can never silently collide with
    (overwrite) another report's filename. Callers decide
    `is_default_configuration` themselves (this function has no
    strategy-specific notion of "default" to compare against).
    """
    date_from = requested_start.value.strftime("%Y%m%d")
    date_to = requested_end.value.strftime("%Y%m%d")
    base = f"{strategy_key}_{instrument.symbol}_{granularity.value}_{date_from}_{date_to}"
    if not is_default_configuration:
        base = f"{base}_{config_identifier(strategy_parameters)}"
    return f"{base}.json"
