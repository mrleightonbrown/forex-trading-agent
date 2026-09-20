"""FX-38H: economically-sealed evaluation-window backtesting.

Motivated by external review of FX-38: that story ran ONE continuous
backtest per (strategy, instrument) across the strategy's entire
available history, then split the resulting trades into development/
holdout buckets by `entry_time` alone. A trade whose entry fell in one
period but whose EXIT fell in the other (a boundary-straddling trade)
would then have its whole P&L attributed to the entry period's bucket
-- including an exit price from a candle in the OTHER period. That is a
real, if usually small, leak of information across a boundary meant to
separate "already-inspected" from "genuinely unseen" data. (FX-38H's
own analysis quantifies exactly how many such trades existed in FX-38
and their effect -- see `scripts/run_fx38h_analysis.py`.)

An evaluation window is "economically sealed" when:
  - indicators MAY see explicit warm-up data from strictly before the
    window (so early-window decisions aren't handicapped by a
    cold-started indicator) -- this is legitimate: a real continuously-
    running strategy would also enter any given day already warmed up;
  - the portfolio starts FLAT at the window's own first candle -- any
    position a strategy would have held purely from warm-up-period
    hypotheses is discarded, never carried in;
  - no trade's entry OR exit price may come from a candle outside the
    window;
  - a position still open when the window's own candles run out is
    force-closed at the window's OWN LAST candle's close, never
    carried past it.

`simulate_trades` (FX-11/FX-11H/FX-18) already implements exactly this
last set of properties -- next-bar-open execution, force-close at the
end of WHATEVER `candles` it's given, and "a hypothesis on the final
candle cannot execute" -- for whatever candle list it receives. This
module's own job is narrower and sits one layer above: run the
strategy continuously over `warmup_candles + window_candles` (so its
indicator state is genuinely warmed up), then discard every hypothesis
generated before the window itself starts, before handing the
survivors to `simulate_trades` alongside ONLY `window_candles` -- never
`warmup_candles`. `simulate_trades`'s own existing boundary behavior
then naturally applies at the WINDOW's edges rather than the full
history's, with no change to `simulate_trades` itself.
"""

from collections.abc import Callable

from forex_agent.domain.candle import Candle
from forex_agent.domain.candle_series import require_consistent_series
from forex_agent.domain.trade_hypothesis import TradeHypothesis


def run_sealed_window_backtest(
    run: Callable[[list[Candle]], list[TradeHypothesis]],
    warmup_candles: list[Candle],
    window_candles: list[Candle],
) -> list[TradeHypothesis]:
    """Runs `run` (a caller-supplied `run_backtest`/`run_backtest_
    incremental` invocation over some strategy) continuously across
    `warmup_candles + window_candles`, then returns only the
    hypotheses generated at or after `window_candles[0].start_time`.

    Callers must pass `window_candles` (alongside these hypotheses, not
    `warmup_candles`) to `simulate_trades` themselves -- this function
    only seals the HYPOTHESIS stream; execution/force-close sealing is
    `simulate_trades`'s own existing, unmodified behavior, applied here
    by construction (window-only candles in, window-only hypotheses
    in) rather than by any new logic.

    Raises `ValueError` if `window_candles` is empty (an empty window
    has nothing to evaluate) or if `warmup_candles + window_candles`
    isn't itself a valid, strictly-ascending, single-instrument,
    single-granularity series (`require_consistent_series`) -- e.g. if
    the two lists are out of order or overlap.
    """
    if not window_candles:
        raise ValueError("window_candles must not be empty")

    combined = warmup_candles + window_candles
    require_consistent_series(combined)

    hypotheses = run(combined)

    window_start = window_candles[0].start_time
    return [h for h in hypotheses if h.generated_at.value >= window_start.value]
