"""FX-16: time-series momentum — deliberately minimal.

Not RSI+MACD+ROC+stochastic combined into one "momentum" strategy, where
nothing would be attributable. Just the N-bar return against a threshold
(`threshold=0` permitted as the pure baseline; a deadband is a later
parameter choice, not assumed here).

`return = current_close / close_N_bars_ago - 1`, computed on the
synthetic-midpoint close — same convention as EMA (FX-14) and the
close-channel breakout (FX-15). LONG when `return > threshold`, SHORT
when `return < -threshold` — a single symmetric threshold, not
independent positive/negative ones, so a later deadband is just
`threshold > 0` rather than a constructor change.

Fires on every bar the condition holds, same as the close-channel
breakout (FX-15) and for the same reason: there's no edge-detection
concept in this signal's definition, and FX-11's same-direction-repeat-
is-a-no-op already makes repeated firing architecturally safe.
"""

from decimal import Decimal
from typing import ClassVar

from forex_agent.domain.candle import Candle
from forex_agent.domain.target_position import TargetPosition
from forex_agent.domain.trade_hypothesis import TradeHypothesis, params_from_dict


class TimeSeriesMomentumStrategy:
    strategy_key: ClassVar[str] = "time_series_momentum_v1"

    def __init__(
        self,
        lookback: int = 20,
        threshold: Decimal = Decimal("0"),
        strategy_version: str = "1",
    ) -> None:
        if isinstance(lookback, bool) or not isinstance(lookback, int):
            raise TypeError(f"lookback must be an int, got {type(lookback).__name__}")
        if lookback < 1:
            raise ValueError(f"lookback must be at least 1, got {lookback}")
        if not isinstance(threshold, Decimal):
            raise TypeError(f"threshold must be a Decimal, got {type(threshold).__name__}")
        if threshold < 0:
            raise ValueError(f"threshold must not be negative, got {threshold}")
        self.lookback = lookback
        self.threshold = threshold
        self.strategy_version = strategy_version

    def evaluate(self, candles: list[Candle]) -> TradeHypothesis | None:
        if len(candles) < self.lookback + 1:
            return None

        current_close = (candles[-1].bid.close + candles[-1].ask.close) / 2
        prior_candle = candles[-(self.lookback + 1)]
        prior_close = (prior_candle.bid.close + prior_candle.ask.close) / 2
        n_bar_return = current_close / prior_close - 1

        if n_bar_return > self.threshold:
            target_position = TargetPosition.LONG
        elif n_bar_return < -self.threshold:
            target_position = TargetPosition.SHORT
        else:
            return None

        current_candle = candles[-1]
        return TradeHypothesis(
            instrument=current_candle.instrument,
            target_position=target_position,
            generated_at=current_candle.start_time,
            timeframe=current_candle.granularity,
            strategy_key=self.strategy_key,
            strategy_version=self.strategy_version,
            parameters=params_from_dict({"lookback": self.lookback, "threshold": self.threshold}),
            rationale=(
                f"{self.lookback}-bar return {n_bar_return} "
                f"{'exceeds' if target_position is TargetPosition.LONG else 'falls below'} "
                f"threshold {'+' if target_position is TargetPosition.LONG else '-'}"
                f"{self.threshold}"
            ),
        )
