"""FX-29 (lifecycle hardening FX-29H): an `IncrementalStrategy`
counterpart to `EmaCrossoverStrategy` (FX-14) -- same `strategy_key`/
parameters/rationale/logic, same strategy, just computed with
O(1)-per-bar state (`IncrementalSmaSeededEma`) instead of a full
from-scratch EMA recompute every call.

`EmaCrossoverStrategy` itself is UNCHANGED and remains the permanent
ground-truth reference this is parity-tested against (see
`tests/unit/domain/strategies/test_ema_crossover_incremental.py`) --
this file does not replace it, only supplements it for large-scale runs.
"""

from decimal import Decimal
from typing import ClassVar

from forex_agent.domain.candle import Candle
from forex_agent.domain.incremental_ema import IncrementalSmaSeededEma
from forex_agent.domain.target_position import TargetPosition
from forex_agent.domain.trade_hypothesis import TradeHypothesis, params_from_dict


class IncrementalEmaCrossoverStrategy:
    strategy_key: ClassVar[str] = "ema_crossover_v1"  # same key as EmaCrossoverStrategy

    def __init__(
        self, fast_period: int = 20, slow_period: int = 50, strategy_version: str = "1"
    ) -> None:
        if isinstance(fast_period, bool) or not isinstance(fast_period, int):
            raise TypeError(f"fast_period must be an int, got {type(fast_period).__name__}")
        if isinstance(slow_period, bool) or not isinstance(slow_period, int):
            raise TypeError(f"slow_period must be an int, got {type(slow_period).__name__}")
        if fast_period < 1:
            raise ValueError(f"fast_period must be at least 1, got {fast_period}")
        if fast_period >= slow_period:
            raise ValueError(
                "fast_period must be less than slow_period, got "
                f"fast_period={fast_period}, slow_period={slow_period}"
            )
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.strategy_version = strategy_version
        self.reset()

    def reset(self) -> None:
        self._fast_ema = IncrementalSmaSeededEma(self.fast_period)
        self._slow_ema = IncrementalSmaSeededEma(self.slow_period)
        self._previous_diff: Decimal | None = None

    def on_candle(self, candle: Candle) -> TradeHypothesis | None:
        close = (candle.bid.close + candle.ask.close) / 2
        fast = self._fast_ema.update(close)
        slow = self._slow_ema.update(close)

        if fast is None or slow is None:
            return None

        current_diff = fast - slow

        if self._previous_diff is None:
            # First bar with both EMAs available -- matches the slow
            # strategy's own `len(candles) < slow_period + 1` guard: a
            # crossover needs a PRIOR diff to compare against, which
            # doesn't exist yet on the very first available bar.
            self._previous_diff = current_diff
            return None

        previous_diff = self._previous_diff
        self._previous_diff = current_diff

        if previous_diff <= 0 and current_diff > 0:
            target_position = TargetPosition.LONG
        elif previous_diff >= 0 and current_diff < 0:
            target_position = TargetPosition.SHORT
        else:
            return None

        crossed = "above" if target_position is TargetPosition.LONG else "below"
        return TradeHypothesis(
            instrument=candle.instrument,
            target_position=target_position,
            generated_at=candle.start_time,
            timeframe=candle.granularity,
            strategy_key=self.strategy_key,
            strategy_version=self.strategy_version,
            parameters=params_from_dict(
                {"fast_period": self.fast_period, "slow_period": self.slow_period}
            ),
            rationale=f"EMA{self.fast_period} crossed {crossed} EMA{self.slow_period}",
        )
