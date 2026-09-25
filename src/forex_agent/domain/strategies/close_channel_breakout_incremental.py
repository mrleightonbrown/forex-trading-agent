"""FX-47: an `IncrementalStrategy` counterpart to
`CloseChannelBreakoutStrategy` (FX-15) -- same `strategy_key`/
parameters/rationale/logic, same strategy, just computed with a small
rolling-window deque instead of re-slicing and re-scanning the full
close history on every call.

`CloseChannelBreakoutStrategy` itself is UNCHANGED and remains the
permanent ground-truth reference this is parity-tested against (see
`tests/unit/domain/strategies/test_close_channel_breakout_incremental.py`).

Needed because FX-47 requires a full-history backtest over native H1
candles (~138,000 bars per instrument) -- the slow strategy's own
`evaluate()` re-derives the whole close list from `candles` every call,
making `run_backtest` (which reslices `candles[:i+1]` per bar) O(n^2)
and intractable at that scale, exactly the performance problem FX-29
already solved for every other O(n^2)-prone strategy in this suite.
"""

from collections import deque
from decimal import Decimal
from typing import ClassVar

from forex_agent.domain.candle import Candle
from forex_agent.domain.target_position import TargetPosition
from forex_agent.domain.trade_hypothesis import TradeHypothesis, params_from_dict


class IncrementalCloseChannelBreakoutStrategy:
    strategy_key: ClassVar[str] = "close_channel_breakout_v1"

    def __init__(self, lookback: int = 20, strategy_version: str = "1") -> None:
        if isinstance(lookback, bool) or not isinstance(lookback, int):
            raise TypeError(f"lookback must be an int, got {type(lookback).__name__}")
        if lookback < 1:
            raise ValueError(f"lookback must be at least 1, got {lookback}")
        self.lookback = lookback
        self.strategy_version = strategy_version
        self.reset()

    def reset(self) -> None:
        self._window: deque[Decimal] = deque(maxlen=self.lookback)
        self._candles_seen = 0

    def on_candle(self, candle: Candle) -> TradeHypothesis | None:
        close = (candle.bid.close + candle.ask.close) / 2

        # Window BEFORE this bar (strictly-before, matching the slow
        # strategy's own `closes[-(lookback+1):-1]` slice) -- read before
        # appending this bar's own close.
        window = list(self._window)
        self._window.append(close)
        self._candles_seen += 1

        if self._candles_seen < self.lookback + 1:
            return None

        window_max = max(window)
        window_min = min(window)

        if close > window_max:
            target_position = TargetPosition.LONG
            rationale = f"close {close} broke above {self.lookback}-bar high {window_max}"
        elif close < window_min:
            target_position = TargetPosition.SHORT
            rationale = f"close {close} broke below {self.lookback}-bar low {window_min}"
        else:
            return None

        return TradeHypothesis(
            instrument=candle.instrument,
            target_position=target_position,
            generated_at=candle.start_time,
            timeframe=candle.granularity,
            strategy_key=self.strategy_key,
            strategy_version=self.strategy_version,
            parameters=params_from_dict({"lookback": self.lookback}),
            rationale=rationale,
        )
