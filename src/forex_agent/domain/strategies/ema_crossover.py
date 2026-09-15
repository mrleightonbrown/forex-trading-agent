"""FX-14: the reference strategy — deliberately boring, per the roadmap
(docs/DECISIONS.md, 2026-09-15). No ADX filter, no RSI, no extra
confirmation, no optimization.

LONG when the fast EMA crosses above the slow EMA; SHORT when it crosses
below. Computed on the synthetic-midpoint close (`(bid.close + ask.close)
/ 2`) — same convention as ADX (FX-12H): a trend signal is a
market-structure question, not an execution-price one.

EMA is SMA-seeded (first value = simple average of the first `period`
closes, standard recurrence after) — the conventional seeding, chosen so
this is independently verifiable against outside references, same
reasoning as Wilder's smoothing in ADX.
"""

from decimal import Decimal
from typing import ClassVar

from forex_agent.domain.candle import Candle
from forex_agent.domain.trade_hypothesis import TradeHypothesis, params_from_dict
from forex_agent.domain.trade_side import TradeSide


class EmaCrossoverStrategy:
    """`ema_crossover_v1` — named for the algorithm, not `TrendStrategy`:
    there will be more than one trend strategy eventually."""

    strategy_key: ClassVar[str] = "ema_crossover_v1"

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

    def evaluate(self, candles: list[Candle]) -> TradeHypothesis | None:
        if len(candles) < self.slow_period + 1:
            return None

        closes = [(c.bid.close + c.ask.close) / 2 for c in candles]
        fast_ema = _sma_seeded_ema(closes, self.fast_period)
        slow_ema = _sma_seeded_ema(closes, self.slow_period)

        current_diff = fast_ema[-1] - slow_ema[-1]
        previous_diff = fast_ema[-2] - slow_ema[-2]

        if previous_diff <= 0 and current_diff > 0:
            side = TradeSide.LONG
        elif previous_diff >= 0 and current_diff < 0:
            side = TradeSide.SHORT
        else:
            return None

        current_candle = candles[-1]
        crossed = "above" if side is TradeSide.LONG else "below"
        return TradeHypothesis(
            instrument=current_candle.instrument,
            side=side,
            generated_at=current_candle.start_time,
            timeframe=current_candle.granularity,
            strategy_key=self.strategy_key,
            strategy_version=self.strategy_version,
            parameters=params_from_dict(
                {"fast_period": self.fast_period, "slow_period": self.slow_period}
            ),
            rationale=f"EMA{self.fast_period} crossed {crossed} EMA{self.slow_period}",
        )


def _sma_seeded_ema(closes: list[Decimal], period: int) -> list[Decimal]:
    """EMA values starting at `closes[period - 1]` — SMA-seeded, standard
    recurrence after. Length = `len(closes) - period + 1`. Assumes
    `len(closes) >= period` — checked by the caller."""
    multiplier = Decimal(2) / Decimal(period + 1)
    seed = sum(closes[:period], Decimal(0)) / period
    values = [seed]
    previous = seed
    for close in closes[period:]:
        previous = close * multiplier + previous * (1 - multiplier)
        values.append(previous)
    return values
