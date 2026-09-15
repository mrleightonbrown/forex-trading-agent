"""FX-19: mean reversion via a Bollinger-Bands-style z-score — the fourth
concrete strategy, and the first to emit `TargetPosition.FLAT` (FX-18).

LONG when the current close is `entry_threshold` population standard
deviations below its own `period`-bar rolling mean (oversold); SHORT when
that far above (overbought); FLAT when the z-score crosses back through
zero (the position thesis has played out) — detected the same way as
EMA's previous/current diff crossing (FX-14), not a magnitude deadband,
so this literally implements "exit at z=0.0" rather than approximating
it with an arbitrary threshold. Anything else (an extreme z that hasn't
crossed yet, or a mid-range z with no crossing) is `None`: hold whatever
position is already open.

Computed on the synthetic-midpoint close, same convention as every prior
strategy (FX-12H/14/15/16). The rolling window INCLUDES the current bar
— the standard Bollinger Bands definition, confirmed before implementing
(see docs/DECISIONS.md) — which means an extreme move slightly inflates
the very standard deviation used to judge it. A known, accepted property
of real Bollinger trading, not a bug.

Standard deviation is population (divide by `period`, not `period - 1`),
computed with `Decimal.sqrt()` — same technique as `backtest_metrics.py`'s
Sharpe/Sortino.
"""

from decimal import Decimal
from typing import ClassVar

from forex_agent.domain.candle import Candle
from forex_agent.domain.target_position import TargetPosition
from forex_agent.domain.trade_hypothesis import TradeHypothesis, params_from_dict


class MeanReversionStrategy:
    strategy_key: ClassVar[str] = "mean_reversion_v1"

    def __init__(
        self,
        period: int = 20,
        entry_threshold: Decimal = Decimal("2.0"),
        strategy_version: str = "1",
    ) -> None:
        if isinstance(period, bool) or not isinstance(period, int):
            raise TypeError(f"period must be an int, got {type(period).__name__}")
        if period < 2:
            # A 1-bar window has zero variance by construction (nothing to
            # deviate from), so period=1 would silently never produce a
            # z-score at all.
            raise ValueError(f"period must be at least 2, got {period}")
        if not isinstance(entry_threshold, Decimal):
            raise TypeError(
                f"entry_threshold must be a Decimal, got {type(entry_threshold).__name__}"
            )
        if entry_threshold <= 0:
            # At 0, `current_z <= -0` and `current_z >= 0` jointly cover
            # the entire real line (FX-21H.1) -- the FLAT zero-crossing
            # branch below becomes unreachable dead code, the opposite
            # of this strategy's whole point.
            raise ValueError(f"entry_threshold must be positive, got {entry_threshold}")
        self.period = period
        self.entry_threshold = entry_threshold
        self.strategy_version = strategy_version

    def evaluate(self, candles: list[Candle]) -> TradeHypothesis | None:
        if len(candles) < self.period + 1:
            return None

        closes = [(c.bid.close + c.ask.close) / 2 for c in candles]
        current_z = _z_score(closes[-self.period :])
        if current_z is None:
            return None

        current_candle = candles[-1]

        if current_z <= -self.entry_threshold:
            return self._hypothesis(
                current_candle,
                TargetPosition.LONG,
                f"z-score {current_z} <= -{self.entry_threshold}: "
                f"{self.period}-bar oversold, reversion long",
            )
        if current_z >= self.entry_threshold:
            return self._hypothesis(
                current_candle,
                TargetPosition.SHORT,
                f"z-score {current_z} >= {self.entry_threshold}: "
                f"{self.period}-bar overbought, reversion short",
            )

        previous_z = _z_score(closes[-self.period - 1 : -1])
        if previous_z is not None and previous_z * current_z <= 0:
            return self._hypothesis(
                current_candle,
                TargetPosition.FLAT,
                f"z-score reverted through the mean ({previous_z} -> {current_z}): closing to flat",
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
                {"period": self.period, "entry_threshold": self.entry_threshold}
            ),
            rationale=rationale,
        )


def _z_score(window: list[Decimal]) -> Decimal | None:
    """Population z-score of the window's LAST element against the whole
    window's own mean/stddev. `None` if the window has zero variance (a
    z-score is undefined when every value in the window is identical) —
    the caller treats that as "no signal", not an error."""
    n = len(window)
    mean = sum(window, Decimal(0)) / n
    variance = sum(((x - mean) ** 2 for x in window), Decimal(0)) / n
    if variance == 0:
        return None
    stddev = variance.sqrt()
    return (window[-1] - mean) / stddev
