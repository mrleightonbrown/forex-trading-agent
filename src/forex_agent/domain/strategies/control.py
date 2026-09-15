"""FX-22: control strategies — not trading ideas, a no-skill scoreboard
every real strategy's `compute_metrics` (FX-17) output gets compared
against on the same sample. Without them, a modestly positive Sharpe
can't be distinguished from sample drift.

Grouped in one file, a deliberate departure from every prior strategy's
one-file-per-strategy convention: these are explicitly a matched
baseline *set*, not independently evolving trading ideas, and each is
only a few lines. All four are genuine `Strategy` implementations, run
through the unmodified `run_backtest`/`simulate_trades`/`compute_metrics`
pipeline like any real strategy — no special-casing.
"""

from typing import ClassVar

from forex_agent.domain.candle import Candle
from forex_agent.domain.target_position import TargetPosition
from forex_agent.domain.trade_hypothesis import TradeHypothesis


class AlwaysLongStrategy:
    """Emits `LONG` unconditionally, every bar. Combined with FX-11's
    same-direction-no-op rule, the position opens once and holds to the
    end of the dataset — a genuine buy-and-hold baseline, not a repeated
    no-op re-entering every bar."""

    strategy_key: ClassVar[str] = "always_long_v1"

    def __init__(self, strategy_version: str = "1") -> None:
        self.strategy_version = strategy_version

    def evaluate(self, candles: list[Candle]) -> TradeHypothesis | None:
        if not candles:
            return None
        current = candles[-1]
        return TradeHypothesis(
            instrument=current.instrument,
            target_position=TargetPosition.LONG,
            generated_at=current.start_time,
            timeframe=current.granularity,
            strategy_key=self.strategy_key,
            strategy_version=self.strategy_version,
            parameters=(),
            rationale="always long: buy-and-hold baseline",
        )


class AlwaysShortStrategy:
    """Symmetric to `AlwaysLongStrategy` — a sell-and-hold baseline."""

    strategy_key: ClassVar[str] = "always_short_v1"

    def __init__(self, strategy_version: str = "1") -> None:
        self.strategy_version = strategy_version

    def evaluate(self, candles: list[Candle]) -> TradeHypothesis | None:
        if not candles:
            return None
        current = candles[-1]
        return TradeHypothesis(
            instrument=current.instrument,
            target_position=TargetPosition.SHORT,
            generated_at=current.start_time,
            timeframe=current.granularity,
            strategy_key=self.strategy_key,
            strategy_version=self.strategy_version,
            parameters=(),
            rationale="always short: sell-and-hold baseline",
        )


class PreviousBarDirectionStrategy:
    """`LONG` if the most recently completed bar's close is above the one
    before it, `SHORT` if below, `None` if equal or there isn't yet a
    second bar to compare against. A naive momentum-chasing baseline,
    deliberately distinct from `TimeSeriesMomentumStrategy`'s N-bar-
    return-vs-threshold design (FX-16) — this one has no lookback and no
    threshold, just whether the last bar went up or down."""

    strategy_key: ClassVar[str] = "previous_bar_direction_v1"

    def __init__(self, strategy_version: str = "1") -> None:
        self.strategy_version = strategy_version

    def evaluate(self, candles: list[Candle]) -> TradeHypothesis | None:
        if len(candles) < 2:
            return None

        current_close = (candles[-1].bid.close + candles[-1].ask.close) / 2
        previous_close = (candles[-2].bid.close + candles[-2].ask.close) / 2

        if current_close > previous_close:
            target_position = TargetPosition.LONG
        elif current_close < previous_close:
            target_position = TargetPosition.SHORT
        else:
            return None

        current_candle = candles[-1]
        direction = "up" if target_position is TargetPosition.LONG else "down"
        return TradeHypothesis(
            instrument=current_candle.instrument,
            target_position=target_position,
            generated_at=current_candle.start_time,
            timeframe=current_candle.granularity,
            strategy_key=self.strategy_key,
            strategy_version=self.strategy_version,
            parameters=(),
            rationale=f"previous bar closed {direction}",
        )


class NoTradeStrategy:
    """The zero baseline: always `None`. `compute_metrics` can't even be
    called on its output (it raises on an empty trade list) -- which is
    itself the point: a real strategy must clear that bar just to be
    comparable at all."""

    strategy_key: ClassVar[str] = "no_trade_v1"

    def __init__(self, strategy_version: str = "1") -> None:
        self.strategy_version = strategy_version

    def evaluate(self, candles: list[Candle]) -> TradeHypothesis | None:
        return None
