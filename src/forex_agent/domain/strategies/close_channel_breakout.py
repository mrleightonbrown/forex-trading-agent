"""FX-15: close-based breakout ("close-channel"), deliberately not a
high/low Donchian channel.

FX-12H already established that our synthetic bid/ask-averaged highs/lows
are an approximation (the two sides' period extrema can occur at
different instants), while bid-close and ask-close are the same instant
and average cleanly. A true high/low Donchian channel becomes testable
once real provider mid OHLC is stored — still deferred (see
docs/DECISIONS.md).

LONG when the current close exceeds the highest close of the `lookback`
bars strictly before it; SHORT when it falls below the lowest of those
same bars. The current bar is never included in computing the channel
it's tested against. Fires on every bar the condition holds, not just the
first breakout — FX-11's close-and-reverse exit rule already treats a
same-direction repeat as a no-op, so this can't create duplicate
positions.
"""

from typing import ClassVar

from forex_agent.domain.candle import Candle
from forex_agent.domain.trade_hypothesis import TradeHypothesis, params_from_dict
from forex_agent.domain.trade_side import TradeSide


class CloseChannelBreakoutStrategy:
    strategy_key: ClassVar[str] = "close_channel_breakout_v1"

    def __init__(self, lookback: int = 20, strategy_version: str = "1") -> None:
        if isinstance(lookback, bool) or not isinstance(lookback, int):
            raise TypeError(f"lookback must be an int, got {type(lookback).__name__}")
        if lookback < 1:
            raise ValueError(f"lookback must be at least 1, got {lookback}")
        self.lookback = lookback
        self.strategy_version = strategy_version

    def evaluate(self, candles: list[Candle]) -> TradeHypothesis | None:
        if len(candles) < self.lookback + 1:
            return None

        closes = [(c.bid.close + c.ask.close) / 2 for c in candles]
        window = closes[-(self.lookback + 1) : -1]
        current = closes[-1]
        window_max = max(window)
        window_min = min(window)

        if current > window_max:
            side = TradeSide.LONG
            rationale = f"close {current} broke above {self.lookback}-bar high {window_max}"
        elif current < window_min:
            side = TradeSide.SHORT
            rationale = f"close {current} broke below {self.lookback}-bar low {window_min}"
        else:
            return None

        current_candle = candles[-1]
        return TradeHypothesis(
            instrument=current_candle.instrument,
            side=side,
            generated_at=current_candle.start_time,
            timeframe=current_candle.granularity,
            strategy_key=self.strategy_key,
            strategy_version=self.strategy_version,
            parameters=params_from_dict({"lookback": self.lookback}),
            rationale=rationale,
        )
