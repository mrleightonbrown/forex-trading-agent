"""FX-20: volatility expansion breakout — the fifth concrete strategy,
combining a Donchian-channel range breakout with an ATR14/ATR50-style
volatility expansion filter. A breakout with no volatility expansion
behind it is not traded.

LONG when the current close breaks above the highest high of the
`breakout_lookback` bars strictly before it AND the short-period/
long-period ATR ratio is at least `expansion_threshold`; SHORT
symmetrically on a breakdown below the lowest low. FLAT when the
expansion itself ends — the ATR ratio crosses back below
`expansion_threshold`, reusing that same threshold as the exit boundary
rather than a separate made-up deadband (same reasoning FX-19 used for
its zero-crossing exit: this is the literal "expansion ends" condition,
not an approximation of it). Anything else (expansion without a fresh
breakout, or a breakout without expansion) is `None`: hold whatever
position is already open.

True Range and Wilder's ATR smoothing use the same synthetic-midpoint
high/low/close convention and recurrence as `regime_detection.py`'s ADX
(FX-12H) — computed independently here, not shared via a common helper.
Deliberate duplication, matching every other strategy file's existing
self-containment (none of the four prior strategies share their own
synthetic-midpoint-close one-liner either); flagged in
`docs/DECISIONS.md` as a revisit-if-a-third-consumer-appears deferral,
not an oversight.

The Donchian channel is built from actual highs/lows, unlike FX-15's
close-based channel — ATR already requires and accepts the synthetic-
midpoint-averaged highs/lows for True Range, so using the same highs/
lows for the breakout range is consistent with that already-accepted
trade-off, not a new one. The triggering price is still the current
bar's close, same convention as every other strategy — only the
reference channel itself is high/low-based.
"""

from decimal import Decimal
from typing import ClassVar

from forex_agent.domain.candle import Candle
from forex_agent.domain.target_position import TargetPosition
from forex_agent.domain.trade_hypothesis import TradeHypothesis, params_from_dict


class VolatilityExpansionBreakoutStrategy:
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
            # A ratio at or below 1.0 isn't expansion at all -- short-term
            # vol at/below the long-term baseline -- so 1.0 itself is a
            # meaningless threshold, not merely a degenerate one.
            raise ValueError(
                f"expansion_threshold must be greater than 1, got {expansion_threshold}"
            )
        self.short_period = short_period
        self.long_period = long_period
        self.breakout_lookback = breakout_lookback
        self.expansion_threshold = expansion_threshold
        self.strategy_version = strategy_version

    def evaluate(self, candles: list[Candle]) -> TradeHypothesis | None:
        minimum_required = max(self.long_period, self.breakout_lookback) + 1
        if len(candles) < minimum_required:
            return None

        highs = [(c.bid.high + c.ask.high) / 2 for c in candles]
        lows = [(c.bid.low + c.ask.low) / 2 for c in candles]
        closes = [(c.bid.close + c.ask.close) / 2 for c in candles]
        true_range = _true_range_series(highs, lows, closes)

        current_ratio = _ratio(
            _atr(true_range, self.short_period), _atr(true_range, self.long_period)
        )
        current_candle = candles[-1]

        if current_ratio is not None and current_ratio >= self.expansion_threshold:
            window_highs = highs[-self.breakout_lookback - 1 : -1]
            window_lows = lows[-self.breakout_lookback - 1 : -1]
            donchian_high = max(window_highs)
            donchian_low = min(window_lows)
            current_close = closes[-1]

            if current_close > donchian_high:
                return self._hypothesis(
                    current_candle,
                    TargetPosition.LONG,
                    f"close {current_close} broke above {self.breakout_lookback}-bar high "
                    f"{donchian_high} with ATR ratio {current_ratio} "
                    f">= {self.expansion_threshold}",
                )
            if current_close < donchian_low:
                return self._hypothesis(
                    current_candle,
                    TargetPosition.SHORT,
                    f"close {current_close} broke below {self.breakout_lookback}-bar low "
                    f"{donchian_low} with ATR ratio {current_ratio} "
                    f">= {self.expansion_threshold}",
                )
            return None  # expanding, but no fresh breakout this bar: hold

        previous_ratio = _ratio(
            _atr(true_range[:-1], self.short_period), _atr(true_range[:-1], self.long_period)
        )
        if previous_ratio is not None and previous_ratio >= self.expansion_threshold:
            return self._hypothesis(
                current_candle,
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


def _true_range_series(
    highs: list[Decimal], lows: list[Decimal], closes: list[Decimal]
) -> list[Decimal]:
    """True Range for each index; index 0 is a placeholder zero (no
    previous close to compare against) and is never read by `_atr`."""
    n = len(highs)
    true_range = [Decimal(0)] * n
    for i in range(1, n):
        true_range[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    return true_range


def _atr(true_range: list[Decimal], period: int) -> Decimal | None:
    """Wilder-smoothed Average True Range as of the last element of
    `true_range`. `None` if there isn't enough history (`period + 1`
    True-Range-bearing candles) to seed it. Same recurrence shape as
    `regime_detection.py`'s smoothed +DM/-DM/TR, but reports the actual
    divided-through average rather than the internal running-sum form
    ADX keeps for itself."""
    n = len(true_range)
    if n < period + 1:
        return None
    atr = sum(true_range[1 : period + 1], Decimal(0)) / period
    for i in range(period + 1, n):
        atr = ((period - 1) * atr + true_range[i]) / period
    return atr


def _ratio(short_atr: Decimal | None, long_atr: Decimal | None) -> Decimal | None:
    if short_atr is None or long_atr is None or long_atr == 0:
        return None
    return short_atr / long_atr
