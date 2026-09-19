"""FX-29 (lifecycle hardening FX-29H): an `IncrementalStrategy`
counterpart to `EmaCrossoverTrendRegimeGatedStrategy` (FX-28) -- same
`strategy_key`/
parameters/rationale/logic, same strategy, just computed with
O(1)-per-bar state (`IncrementalSmaSeededEma` + `IncrementalAdx`)
instead of a full from-scratch EMA/ADX recompute every call.

`EmaCrossoverTrendRegimeGatedStrategy` itself is UNCHANGED and remains
the permanent ground-truth reference this is parity-tested against (see
`tests/unit/domain/strategies/
test_ema_crossover_trend_regime_gated_incremental.py`).

Look-ahead safety note carried over unchanged from the slow strategy:
the regime classification uses the ADX value as of and including the
current/signal bar -- `IncrementalAdx.update()` is called with this same
bar's high/low/close before the gate decision is made, exactly mirroring
the slow strategy's `classify_regime(candles, ...)` call on the full
prefix through the signal bar.
"""

from decimal import Decimal
from typing import ClassVar

from forex_agent.domain.candle import Candle
from forex_agent.domain.incremental_adx import IncrementalAdx
from forex_agent.domain.incremental_ema import IncrementalSmaSeededEma
from forex_agent.domain.target_position import TargetPosition
from forex_agent.domain.trade_hypothesis import TradeHypothesis, params_from_dict
from forex_agent.domain.trend_regime import TrendRegime


class IncrementalEmaCrossoverTrendRegimeGatedStrategy:
    strategy_key: ClassVar[str] = "ema_crossover_trend_regime_gated_v1"

    def __init__(
        self,
        fast_period: int = 20,
        slow_period: int = 50,
        regime_period: int = 14,
        regime_threshold: Decimal = Decimal("25"),
        strategy_version: str = "1",
    ) -> None:
        _require_period("fast_period", fast_period)
        _require_period("slow_period", slow_period)
        if fast_period >= slow_period:
            raise ValueError(
                "fast_period must be less than slow_period, got "
                f"fast_period={fast_period}, slow_period={slow_period}"
            )
        _require_period("regime_period", regime_period)
        if not isinstance(regime_threshold, Decimal):
            raise TypeError(
                f"regime_threshold must be a Decimal, got {type(regime_threshold).__name__}"
            )
        if not (Decimal(0) <= regime_threshold <= Decimal(100)):
            raise ValueError(f"regime_threshold must be within [0, 100], got {regime_threshold}")

        self.fast_period = fast_period
        self.slow_period = slow_period
        self.regime_period = regime_period
        self.regime_threshold = regime_threshold
        self.strategy_version = strategy_version
        self.reset()

    def reset(self) -> None:
        self._fast_ema = IncrementalSmaSeededEma(self.fast_period)
        self._slow_ema = IncrementalSmaSeededEma(self.slow_period)
        self._previous_diff: Decimal | None = None
        self._adx = IncrementalAdx(self.regime_period)

    def on_candle(self, candle: Candle) -> TradeHypothesis | None:
        high = (candle.bid.high + candle.ask.high) / 2
        low = (candle.bid.low + candle.ask.low) / 2
        close = (candle.bid.close + candle.ask.close) / 2

        fast = self._fast_ema.update(close)
        slow = self._slow_ema.update(close)
        adx = self._adx.update(high, low, close)  # always update, every bar, regardless of signal

        if fast is None or slow is None:
            return None

        current_diff = fast - slow

        if self._previous_diff is None:
            self._previous_diff = current_diff
            return None

        previous_diff = self._previous_diff
        self._previous_diff = current_diff

        if previous_diff <= 0 and current_diff > 0:
            signal = TargetPosition.LONG
        elif previous_diff >= 0 and current_diff < 0:
            signal = TargetPosition.SHORT
        else:
            return None  # no crossover event this bar: nothing to gate

        if adx is None:
            regime = None  # insufficient regime history: treated like RANGING (gated closed)
        else:
            regime = TrendRegime.TRENDING if adx >= self.regime_threshold else TrendRegime.RANGING

        crossed = "above" if signal is TargetPosition.LONG else "below"
        if regime is TrendRegime.TRENDING:
            return self._hypothesis(
                candle,
                signal,
                f"EMA{self.fast_period} crossed {crossed} EMA{self.slow_period}, "
                f"confirmed by TrendRegime.TRENDING",
            )
        return self._hypothesis(
            candle,
            TargetPosition.FLAT,
            f"EMA{self.fast_period} crossed {crossed} EMA{self.slow_period}, "
            f"NOT confirmed (regime={regime}): closing to flat",
        )

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
                    "fast_period": self.fast_period,
                    "slow_period": self.slow_period,
                    "regime_period": self.regime_period,
                    "regime_threshold": self.regime_threshold,
                }
            ),
            rationale=rationale,
        )


def _require_period(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    if value < 1:
        raise ValueError(f"{name} must be at least 1, got {value}")
