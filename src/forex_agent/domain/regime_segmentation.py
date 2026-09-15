"""FX-21 (look-ahead fixed in FX-21H): connects `classify_regime` (FX-12)
and `compute_metrics` (FX-17) to perform ENTRY-REGIME ATTRIBUTION — not
regime-gating. This buckets trades a strategy already took
unconditionally by the `TrendRegime` prevailing at each trade's entry;
it does not change which trades occur. A true regime-*gating* strategy
(one that refuses to enter, or exits to FLAT instead of reversing, when
the regime doesn't match) is a different, unbuilt experiment with its
own real design questions — see `docs/DECISIONS.md`. No strategy is
modified here; regime stays structurally external to every strategy,
exactly as decided when regime detection was first built.

`compute_metrics` needed zero changes for this — it was deliberately
designed (FX-17) to accept any `list[SimulatedTrade]` and report full
stats for exactly that list, so "trending vs. ranging" is just filtering
the trade list before calling it twice. This module supplies that
filter.

FX-21H: the original version of this module classified each trade using
`candles[:entry_index + 1]` — INCLUDING the entry candle's own high/low/
close, none of which are known at the instant of entry (FX-11H:
execution happens at that candle's OPEN; only the open is known then).
That is look-ahead bias, the same class of bug FX-11H fixed in
`simulate_trades` itself. Fixed to `candles[:entry_index]`: only candles
fully completed strictly before entry — the decision candle and
earlier.
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
    to STRICTLY BEFORE the entry bar (FX-21H) — the entry candle itself
    is excluded, since only its open (the execution price, per FX-11H)
    is known at the instant of entry; its high/low/close are not.

    A trade is `unclassified`, not an error, if there isn't yet
    `2 * period` candles of history strictly before its `entry_time` —
    the minimum `classify_regime` itself requires. This is the normal,
    expected case for trades entered early in any backtest, not a
    caller mistake.

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

        history = candles[:entry_index]  # FX-21H: strictly before entry, not including it
        if len(history) < minimum_required:
            unclassified.append(trade)
            continue

        regime = classify_regime(history, period=period, threshold=threshold)
        if regime is TrendRegime.TRENDING:
            trending.append(trade)
        else:
            ranging.append(trade)

    return RegimeSegmentedTrades(trending=trending, ranging=ranging, unclassified=unclassified)
