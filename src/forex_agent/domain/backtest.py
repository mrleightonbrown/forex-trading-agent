"""FX-10: the look-ahead-safe backtest engine.

Replays stored candles to a `Strategy` one bar at a time, collecting the
`TradeHypothesis` values it produces. Deliberately narrow — no
position/trade/P&L simulation here (a separate future story: closing a
backtest position needs its own design decision with no live
risk/execution engine to do it), and no performance optimization for large
candle sets (`candles[:i+1]` reslicing is O(n) per step, O(n^2) overall —
fine for now, revisit once real strategies exist and it matters).
"""

from forex_agent.domain.candle import Candle
from forex_agent.domain.strategy import Strategy, run_strategy
from forex_agent.domain.trade_hypothesis import TradeHypothesis


def run_backtest(strategy: Strategy, candles: list[Candle]) -> list[TradeHypothesis]:
    """Replay `candles` to `strategy` one bar at a time: at step `i`, the
    strategy is only ever given `candles[0:i+1]` — never a later bar. This
    is the actual look-ahead-bias prevention CLAUDE.md requires, not just a
    naming convention.

    Raises `ValueError` if the candles span more than one instrument or
    granularity, aren't strictly ascending by `start_time`, or if a
    returned hypothesis isn't timestamped at the current bar's
    `start_time` (a strategy fabricating a hypothesis outside the window it
    was actually shown is itself a look-ahead bug).

    Finalized-only enforcement comes from reusing `run_strategy` for each
    step, not a separate check here.
    """
    if not candles:
        return []

    instrument = candles[0].instrument
    granularity = candles[0].granularity
    previous_start_time = None
    for candle in candles:
        if candle.instrument != instrument:
            raise ValueError("all candles must share the same instrument")
        if candle.granularity != granularity:
            raise ValueError("all candles must share the same granularity")
        if previous_start_time is not None and candle.start_time.value <= previous_start_time.value:
            raise ValueError(
                "candles must be strictly ascending by start_time; "
                f"{candle.start_time.value.isoformat()} does not follow "
                f"{previous_start_time.value.isoformat()}"
            )
        previous_start_time = candle.start_time

    hypotheses: list[TradeHypothesis] = []
    for i, current_bar in enumerate(candles):
        hypothesis = run_strategy(strategy, candles[: i + 1])
        if hypothesis is None:
            continue
        if hypothesis.generated_at != current_bar.start_time:
            raise ValueError(
                "strategy hypothesis generated_at "
                f"({hypothesis.generated_at.value.isoformat()}) must equal the current "
                f"bar's start_time ({current_bar.start_time.value.isoformat()})"
            )
        hypotheses.append(hypothesis)

    return hypotheses
