"""FX-36: an `IncrementalStrategy` counterpart to
`VolatilityExpansionBreakoutStrategy` (FX-20) -- same `strategy_key`/
parameters/rationale/logic, same strategy, just computed with
O(1)-per-bar state (`IncrementalWilderAtr` + a small rolling-window
Donchian tracker) instead of full from-scratch True Range/ATR/Donchian
recomputation every call.

`VolatilityExpansionBreakoutStrategy` itself is UNCHANGED and remains
the permanent ground-truth reference this is parity-tested against
(see `tests/unit/domain/strategies/
test_volatility_expansion_incremental.py`).

Two state-tracking subtleties worth being explicit about, both handled
by keeping slightly more state than the "obvious" minimum:

1. The slow strategy computes an ATR-ratio "as of the bar before this
   one" (`true_range[:-1]`) to decide the FLAT-exit condition,
   separately from "as of this bar" for the LONG/SHORT-entry condition.
   This class keeps `_previous_ratio` -- the ratio computed on the
   PRIOR call, read before this call's ATR trackers are updated --
   exactly mirroring that same before/after distinction incrementally.
2. The slow strategy's overall readiness gate is
   `max(long_period, breakout_lookback) + 1` candles, not just
   "ATR is ready" -- if `breakout_lookback > long_period` (an unusual
   but valid configuration), ATR could become ready before the
   Donchian window fills, and checking ATR readiness alone would let a
   premature FLAT fire before any entry was ever possible. This class
   tracks `_candles_seen` explicitly and gates on the same combined
   condition, not just on the ATR/window's own individual readiness.
"""

from collections import deque
from decimal import Decimal
from typing import ClassVar

from forex_agent.domain.candle import Candle
from forex_agent.domain.incremental_atr import IncrementalWilderAtr
from forex_agent.domain.target_position import TargetPosition
from forex_agent.domain.trade_hypothesis import TradeHypothesis, params_from_dict


class IncrementalVolatilityExpansionBreakoutStrategy:
    strategy_key: ClassVar[str] = "volatility_expansion_breakout_v1"

    def __init__(
        self,
        short_period: int = 14,
        long_period: int = 50,
        breakout_lookback: int = 20,
        expansion_threshold: Decimal = Decimal("1.5"),
        strategy_version: str = "1",
    ) -> None:
        if isinstance(short_period, bool) or not isinstance(short_period, int):
            raise TypeError(f"short_period must be an int, got {type(short_period).__name__}")
        if isinstance(long_period, bool) or not isinstance(long_period, int):
            raise TypeError(f"long_period must be an int, got {type(long_period).__name__}")
        if isinstance(breakout_lookback, bool) or not isinstance(breakout_lookback, int):
            raise TypeError(
                f"breakout_lookback must be an int, got {type(breakout_lookback).__name__}"
            )
        if short_period < 1:
            raise ValueError(f"short_period must be at least 1, got {short_period}")
        if short_period >= long_period:
            raise ValueError(
                "short_period must be less than long_period, got "
                f"short_period={short_period}, long_period={long_period}"
            )
        if breakout_lookback < 1:
            raise ValueError(f"breakout_lookback must be at least 1, got {breakout_lookback}")
        if not isinstance(expansion_threshold, Decimal):
            raise TypeError(
                f"expansion_threshold must be a Decimal, got {type(expansion_threshold).__name__}"
            )
        if expansion_threshold <= 1:
            raise ValueError(
                f"expansion_threshold must be greater than 1, got {expansion_threshold}"
            )
        self.short_period = short_period
        self.long_period = long_period
        self.breakout_lookback = breakout_lookback
        self.expansion_threshold = expansion_threshold
        self.strategy_version = strategy_version
        self.reset()

    def reset(self) -> None:
        self._short_atr = IncrementalWilderAtr(self.short_period)
        self._long_atr = IncrementalWilderAtr(self.long_period)
        self._previous_ratio: Decimal | None = None
        self._window_highs: deque[Decimal] = deque(maxlen=self.breakout_lookback)
        self._window_lows: deque[Decimal] = deque(maxlen=self.breakout_lookback)
        self._candles_seen = 0
        self._minimum_required = max(self.long_period, self.breakout_lookback) + 1

    def on_candle(self, candle: Candle) -> TradeHypothesis | None:
        high = (candle.bid.high + candle.ask.high) / 2
        low = (candle.bid.low + candle.ask.low) / 2
        close = (candle.bid.close + candle.ask.close) / 2

        # Donchian window BEFORE this bar (strictly-before, matching the
        # slow strategy's own `highs[-lookback-1:-1]` slice) -- read
        # before appending this bar's own high/low.
        window_highs = list(self._window_highs)
        window_lows = list(self._window_lows)
        self._window_highs.append(high)
        self._window_lows.append(low)

        previous_ratio = self._previous_ratio
        short_atr = self._short_atr.update(high, low, close)
        long_atr = self._long_atr.update(high, low, close)
        current_ratio = _ratio(short_atr, long_atr)
        self._previous_ratio = current_ratio

        self._candles_seen += 1
        if self._candles_seen < self._minimum_required:
            return None

        if current_ratio is not None and current_ratio >= self.expansion_threshold:
            donchian_high = max(window_highs)
            donchian_low = min(window_lows)

            if close > donchian_high:
                return self._hypothesis(
                    candle,
                    TargetPosition.LONG,
                    f"close {close} broke above {self.breakout_lookback}-bar high "
                    f"{donchian_high} with ATR ratio {current_ratio} "
                    f">= {self.expansion_threshold}",
                )
            if close < donchian_low:
                return self._hypothesis(
                    candle,
                    TargetPosition.SHORT,
                    f"close {close} broke below {self.breakout_lookback}-bar low "
                    f"{donchian_low} with ATR ratio {current_ratio} "
                    f">= {self.expansion_threshold}",
                )
            return None  # expanding, but no fresh breakout this bar: hold

        if previous_ratio is not None and previous_ratio >= self.expansion_threshold:
            return self._hypothesis(
                candle,
                TargetPosition.FLAT,
                f"ATR ratio contracted below {self.expansion_threshold} "
                f"({previous_ratio} -> {current_ratio}): closing to flat",
            )

        return None

    def _hypothesis(
        self, current_candle: Candle, target_position: TargetPosition, rationale: str
    ) -> TradeHypothesis:
        return TradeHypothesis(
            instrument=current_candle.instrument,
            target_position=target_position,
            generated_at=current_candle.start_time,
            timeframe=current_candle.granularity,
            strategy_key=self.strategy_key,
            strategy_version=self.strategy_version,
            parameters=params_from_dict(
                {
                    "short_period": self.short_period,
                    "long_period": self.long_period,
                    "breakout_lookback": self.breakout_lookback,
                    "expansion_threshold": self.expansion_threshold,
                }
            ),
            rationale=rationale,
        )


def _ratio(short_atr: Decimal | None, long_atr: Decimal | None) -> Decimal | None:
    if short_atr is None or long_atr is None or long_atr == 0:
        return None
    return short_atr / long_atr
