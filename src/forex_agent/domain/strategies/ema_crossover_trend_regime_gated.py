"""FX-28: EMA crossover, gated by `TrendRegime` (FX-12's ADX classifier) —
the true regime-*gating* counterpart to FX-21/FX-23's entry-regime
*attribution* and FX-25's H4-confirmation gating.

Same SMA-seeded EMA crossover *event* as `EmaCrossoverStrategy` (FX-14),
computed independently here — self-contained, matching every prior
strategy file's convention, not imported from `ema_crossover.py`.

Gate: `classify_regime` is direction-agnostic (ADX measures trend
*strength*, not direction), so both LONG and SHORT crossover events
require the SAME condition: `TrendRegime.TRENDING`. `RANGING`, or
insufficient regime history (`< 2 * regime_period` candles), gates the
signal to FLAT rather than ignoring it — exactly
`MultiTimeframeTrendStrategy`'s already-settled FLAT-vs-None precedent
(FX-25/FX-21H's own resolved "reversal-vs-FLAT" design question), just
gated by ADX instead of a second timeframe's EMA state. No crossover
event this bar -> None, regardless of regime.

Look-ahead safety: the regime classification uses the exact same
`candles` prefix `evaluate()` was handed (through and including the
current/signal bar) -- not a further-truncated slice. This is not a new
look-ahead argument: it is exactly equivalent to FX-21H's own established
convention in `regime_segmentation.segment_trades_by_regime`
(`candles[:entry_index]`). Since execution happens at the *next* bar's
open (FX-11H), `entry_index` there always equals the signal bar's index
+ 1, so `candles[:entry_index]` and this strategy's own
`evaluate(candles)` are the identical prefix -- verified directly before
relying on it, not assumed.
"""

from decimal import Decimal
from typing import ClassVar

from forex_agent.domain.candle import Candle
from forex_agent.domain.regime_detection import classify_regime
from forex_agent.domain.target_position import TargetPosition
from forex_agent.domain.trade_hypothesis import TradeHypothesis, params_from_dict
from forex_agent.domain.trend_regime import TrendRegime


class EmaCrossoverTrendRegimeGatedStrategy:
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

    def evaluate(self, candles: list[Candle]) -> TradeHypothesis | None:
        if len(candles) < self.slow_period + 1:
            return None

        closes = [(c.bid.close + c.ask.close) / 2 for c in candles]
        fast_ema = _sma_seeded_ema(closes, self.fast_period)
        slow_ema = _sma_seeded_ema(closes, self.slow_period)
        current_diff = fast_ema[-1] - slow_ema[-1]
        previous_diff = fast_ema[-2] - slow_ema[-2]

        if previous_diff <= 0 and current_diff > 0:
            signal = TargetPosition.LONG
        elif previous_diff >= 0 and current_diff < 0:
            signal = TargetPosition.SHORT
        else:
            return None  # no crossover event this bar: nothing to gate

        current_candle = candles[-1]
        minimum_regime_history = self.regime_period * 2
        if len(candles) >= minimum_regime_history:
            regime = classify_regime(
                candles, period=self.regime_period, threshold=self.regime_threshold
            )
        else:
            regime = None  # insufficient history: treated like RANGING (gated closed)

        crossed = "above" if signal is TargetPosition.LONG else "below"
        if regime is TrendRegime.TRENDING:
            return self._hypothesis(
                current_candle,
                signal,
                f"EMA{self.fast_period} crossed {crossed} EMA{self.slow_period}, "
                f"confirmed by TrendRegime.TRENDING",
            )
        return self._hypothesis(
            current_candle,
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


def _sma_seeded_ema(closes: list[Decimal], period: int) -> list[Decimal]:
    """Same shape as `ema_crossover.py`'s own helper, duplicated per this
    codebase's established per-strategy self-containment convention."""
    multiplier = Decimal(2) / Decimal(period + 1)
    seed = sum(closes[:period], Decimal(0)) / period
    values = [seed]
    previous = seed
    for close in closes[period:]:
        previous = close * multiplier + previous * (1 - multiplier)
        values.append(previous)
    return values
