"""FX-21: connects `classify_regime` (FX-12) and `compute_metrics`
(FX-17) — built for, and only for, the regime-conditioned experiment
story: does filtering a strategy's trades down to one `TrendRegime`
change its metrics? No strategy is modified; regime stays structurally
external to every strategy, exactly as decided when regime detection was
first built (see `docs/DECISIONS.md`).

`compute_metrics` needed zero changes for this — it was deliberately
designed (FX-17) to accept any `list[SimulatedTrade]` and report full
stats for exactly that list, so "trending vs. ranging" is just filtering
the trade list before calling it twice. This module supplies that
filter.
"""

from dataclasses import dataclass
from decimal import Decimal

from forex_agent.domain.candle import Candle
from forex_agent.domain.candle_series import require_consistent_series
from forex_agent.domain.regime_detection import classify_regime
from forex_agent.domain.simulated_trade import SimulatedTrade
from forex_agent.domain.trend_regime import TrendRegime


@dataclass(frozen=True, slots=True)
class RegimeSegmentedTrades:
    trending: list[SimulatedTrade]
    ranging: list[SimulatedTrade]
    unclassified: list[SimulatedTrade]


def segment_trades_by_regime(
    trades: list[SimulatedTrade],
    candles: list[Candle],
    *,
    period: int = 14,
    threshold: Decimal = Decimal("25"),
) -> RegimeSegmentedTrades:
    """Buckets `trades` by the `TrendRegime` in effect at each trade's
    `entry_time`, classified via `classify_regime` on `candles` truncated
    to (and including) that bar — never a look-ahead: only history up to
    and including the entry bar is used to judge it.

    A trade is `unclassified`, not an error, if there isn't yet
    `2 * period` candles of history at its `entry_time` — the minimum
    `classify_regime` itself requires. This is the normal, expected case
    for trades entered early in any backtest, not a caller mistake.

    Raises `ValueError` if `candles` fails `require_consistent_series`
    (one instrument, one granularity, strictly ascending), or if any
    trade's `instrument` doesn't match the candles' instrument, or if any
    trade's `entry_time` doesn't correspond to any candle's `start_time`
    — all caller errors, same defensive philosophy as `simulate_trades`
    (FX-11H): a mismatched trade/candle pairing is not silently dropped.
    """
    instrument, _granularity = require_consistent_series(candles)

    time_to_index = {candle.start_time: i for i, candle in enumerate(candles)}
    minimum_required = period * 2

    trending: list[SimulatedTrade] = []
    ranging: list[SimulatedTrade] = []
    unclassified: list[SimulatedTrade] = []

    for trade in trades:
        if trade.instrument != instrument:
            raise ValueError(
                f"trade instrument ({trade.instrument.symbol}) does not match "
                f"the candle series' instrument ({instrument.symbol})"
            )
        entry_index = time_to_index.get(trade.entry_time)
        if entry_index is None:
            raise ValueError(
                f"trade entry_time {trade.entry_time.value.isoformat()} does not "
                "correspond to any candle's start_time"
            )

        history = candles[: entry_index + 1]
        if len(history) < minimum_required:
            unclassified.append(trade)
            continue

        regime = classify_regime(history, period=period, threshold=threshold)
        if regime is TrendRegime.TRENDING:
            trending.append(trade)
        else:
            ranging.append(trade)

    return RegimeSegmentedTrades(trending=trending, ranging=ranging, unclassified=unclassified)
