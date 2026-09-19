"""FX-29 (lifecycle hardening FX-29H): the incremental counterpart to
`strategy.py`'s `Strategy`/`run_backtest`.

`Strategy.evaluate(candles: list[Candle])` is handed the FULL history-so-
far on every bar by `run_backtest` -- correct, but O(n) per call, so
O(n^2) over a full backtest, worse once a strategy's own internal
indicator computation is *also* O(len(candles)) per call (every existing
strategy's own `_sma_seeded_ema`, or `classify_regime`). `IncrementalStrategy`
is handed exactly one NEW candle per call and is responsible for keeping
whatever state it needs itself (see `incremental_ema`/`incremental_adx`)
-- `run_backtest_incremental` never reslices or re-hands old candles.

Deliberately a NEW, separate abstraction rather than a change to
`Strategy` itself -- every existing concrete strategy (7 of them, plus
`MultiTimeframeTrendStrategy`) keeps working exactly as before, and the
slow `Strategy`/`run_backtest`/`simulate_trades` path remains the
permanent ground-truth reference incremental strategies are parity-
tested against (see `tests/unit/domain/strategies/test_ema_crossover_
incremental.py` and the sibling gated test).

FX-29H: found live (external review, independently reproduced before
fixing) -- an `IncrementalStrategy` is stateful, so calling
`run_backtest_incremental` twice with the SAME instance silently
produced different results the second time (state left over from the
first run). Worse: if the second run raised partway through (e.g. a
non-finalized candle), the strategy was left with partially-mutated
state from whatever candles it *did* process before the raise, so even
a subsequent *correct* call on that same instance no longer matched a
fresh instance's output. Fixed two ways: (1) `IncrementalStrategy`
gained `reset()`, called truly unconditionally at the very start of
every `run_backtest_incremental` call -- before even the empty-`candles`
early return, not just before validation/replay (a second round of
review caught that the first version of this fix still skipped `reset()`
on an empty list, despite this same claim of "unconditionally" already
being written down -- fixed by moving the call, not by softening the
claim). Reusing an instance across replay calls is no longer silently
wrong, matching `run_backtest`'s own implicit "each call is independent"
semantics. (2) `candles` is validated IN FULL (including every candle's
finalized status) before any `on_candle()` call -- an invalid input
series is rejected before any replay can partially mutate state.

`reset()` is kept on the strategy itself (not, say, always constructing
a fresh instance internally from a factory) deliberately: the same
`IncrementalStrategy` object is meant to be reusable directly in a
future live/paper streaming mode, where there's no "replay" to reset
before -- only `run_backtest_incremental`, the historical replay driver,
needs to reset one before use.
"""

from typing import Protocol

from forex_agent.domain.candle import Candle
from forex_agent.domain.candle_series import require_consistent_series
from forex_agent.domain.trade_hypothesis import TradeHypothesis


class IncrementalStrategy(Protocol):
    """Same contract as `Strategy`, one bar at a time, but stateful --
    implementations must assume every candle is already finalized
    (`run_backtest_incremental` validates that up front, before calling
    `on_candle` at all)."""

    def reset(self) -> None:
        """Clear all internal state back to what a freshly-constructed
        instance would have. Called truly unconditionally by
        `run_backtest_incremental` -- the very first thing it does, even
        before an empty-`candles` early return -- so reusing an instance
        across calls must never silently carry state over, regardless of
        what that call's `candles` turns out to be."""
        ...

    def on_candle(self, candle: Candle) -> TradeHypothesis | None: ...


def run_backtest_incremental(
    strategy: IncrementalStrategy, candles: list[Candle]
) -> list[TradeHypothesis]:
    """Replay `candles` to `strategy` one bar at a time, in one O(n) pass
    -- `strategy.on_candle(candle)` is called exactly once per candle, in
    order, with no candle ever re-shown. Same validation and same
    no-look-ahead guarantee as `run_backtest`: every hypothesis returned
    must be timestamped at the candle that produced it, for the same
    instrument, at the same granularity; every candle must already be
    finalized. A stronger structural guarantee than the slow path, in
    fact -- `IncrementalStrategy` cannot even be handed a future candle
    by construction, whereas the slow path's safety depends on
    `run_backtest` slicing correctly.

    FX-29H: `strategy.reset()` is called truly unconditionally -- first,
    before even the empty-`candles` early return, not just before
    validation/replay. (An earlier version of this fix called it after
    that early return, so `run_backtest_incremental(strategy, [])`
    silently left a reused strategy's prior state untouched, despite
    this very docstring already claiming "unconditionally" -- caught by
    a second round of external review; fixed by moving the call, not by
    softening the claim.) `candles` is then validated in full --
    including every candle's finalized status -- before `on_candle` is
    ever called, so an invalid series can't leave a strategy
    partially replayed: after any call, successful or not, a strategy's
    state is always either freshly reset (empty input, or validation
    failed before any candle was processed) or fully replayed through
    every candle given (success) -- never a partial mixture of the two.
    """
    strategy.reset()

    if not candles:
        return []

    instrument, _granularity = require_consistent_series(candles)
    for candle in candles:
        if not candle.is_finalized:
            raise ValueError(
                "strategies must only evaluate finalized candles; candle at "
                f"{candle.start_time.value.isoformat()} is not finalized"
            )

    hypotheses: list[TradeHypothesis] = []
    for current_bar in candles:
        hypothesis = strategy.on_candle(current_bar)
        if hypothesis is None:
            continue
        if hypothesis.instrument != instrument:
            raise ValueError(
                f"strategy hypothesis instrument ({hypothesis.instrument.symbol}) does not "
                f"match the candle series' instrument ({instrument.symbol})"
            )
        if hypothesis.generated_at != current_bar.start_time:
            raise ValueError(
                "strategy hypothesis generated_at "
                f"({hypothesis.generated_at.value.isoformat()}) must equal the current "
                f"bar's start_time ({current_bar.start_time.value.isoformat()})"
            )
        if hypothesis.timeframe != current_bar.granularity:
            raise ValueError(
                f"strategy hypothesis timeframe ({hypothesis.timeframe}) does not match "
                f"the candle series' granularity ({current_bar.granularity})"
            )
        hypotheses.append(hypothesis)

    return hypotheses
