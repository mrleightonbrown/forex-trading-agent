"""FX-29: the incremental counterpart to `strategy.py`'s `Strategy`/
`run_backtest`.

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
"""

from typing import Protocol

from forex_agent.domain.candle import Candle
from forex_agent.domain.candle_series import require_consistent_series
from forex_agent.domain.trade_hypothesis import TradeHypothesis


class IncrementalStrategy(Protocol):
    """Same contract as `Strategy`, one bar at a time. Implementations
    must assume every candle is already finalized -- `run_backtest_
    incremental` enforces that before calling `on_candle`, same as
    `run_strategy` does for the slow path."""

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
    """
    if not candles:
        return []

    instrument, _granularity = require_consistent_series(candles)

    hypotheses: list[TradeHypothesis] = []
    for current_bar in candles:
        if not current_bar.is_finalized:
            raise ValueError(
                "strategies must only evaluate finalized candles; candle at "
                f"{current_bar.start_time.value.isoformat()} is not finalized"
            )

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
