"""FX-25: multi-timeframe trend confirmation — the last item on the
original strategy-suite roadmap, deliberately sequenced last and blocked
on resolving H4 candle alignment first (FX-24).

The first strategy needing two candle series at once. `Strategy.
evaluate(candles: list[Candle])`'s signature is unchanged — every other
strategy still implements exactly that. This one takes the full H4
series as a constructor argument (legitimate for backtesting, which
always operates over already-fetched historical data) and internally
filters it, on every `evaluate()` call, to only H4 bars that have fully
closed strictly before the current H1 bar's `start_time`. H4 bucket
boundaries always land exactly on H1 boundaries (both are whole-UTC-hour
quantized, post-FX-24), so `h4_start + 4h <= h1_current_start` is exactly
the right cutoff — not one bar early, not a look-ahead.

H1 signal: the same SMA-seeded EMA crossover *event* as
`EmaCrossoverStrategy` (fires only on the bar the crossover happens),
computed independently here — self-contained, matching every prior
strategy file's convention, not imported from `ema_crossover.py`.

H4 confirmation: NOT a crossover event — the H4 fast/slow EMA's current
*state* (fast > slow = bullish, fast < slow = bearish, equal = neutral).

Gating: H1 LONG + H4 bullish -> LONG. H1 SHORT + H4 bearish -> SHORT.
H1 fires but H4 disagrees (or H4 has insufficient history, or is
neutral) -> FLAT. No H1 event this bar -> None. Because EMA crossovers
structurally alternate direction, a disagreeing new H1 signal is always
opposite to whatever's currently open, so unconditional FLAT (FX-18) is
exactly right: closes an opposing confirmed position, no-ops if already
flat.
"""

from decimal import Decimal
from typing import ClassVar

from forex_agent.domain.candle import Candle
from forex_agent.domain.candle_series import require_consistent_series
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.granularity_duration import fixed_duration
from forex_agent.domain.target_position import TargetPosition
from forex_agent.domain.trade_hypothesis import TradeHypothesis, params_from_dict

_H4_DURATION_SECONDS = fixed_duration(Granularity.H4).total_seconds()


class MultiTimeframeTrendStrategy:
    strategy_key: ClassVar[str] = "multi_timeframe_trend_v1"

    def __init__(
        self,
        h4_candles: list[Candle],
        h1_fast_period: int = 20,
        h1_slow_period: int = 50,
        h4_fast_period: int = 20,
        h4_slow_period: int = 50,
        strategy_version: str = "1",
    ) -> None:
        if h4_candles:
            require_consistent_series(h4_candles)
            for candle in h4_candles:
                if candle.granularity is not Granularity.H4:
                    raise ValueError(
                        f"h4_candles must all be Granularity.H4, got {candle.granularity}"
                    )
        _require_period("h1_fast_period", h1_fast_period)
        _require_period("h1_slow_period", h1_slow_period)
        if h1_fast_period >= h1_slow_period:
            raise ValueError(
                "h1_fast_period must be less than h1_slow_period, got "
                f"h1_fast_period={h1_fast_period}, h1_slow_period={h1_slow_period}"
            )
        _require_period("h4_fast_period", h4_fast_period)
        _require_period("h4_slow_period", h4_slow_period)
        if h4_fast_period >= h4_slow_period:
            raise ValueError(
                "h4_fast_period must be less than h4_slow_period, got "
                f"h4_fast_period={h4_fast_period}, h4_slow_period={h4_slow_period}"
            )

        self.h4_candles = h4_candles
        self.h1_fast_period = h1_fast_period
        self.h1_slow_period = h1_slow_period
        self.h4_fast_period = h4_fast_period
        self.h4_slow_period = h4_slow_period
        self.strategy_version = strategy_version

    def evaluate(self, candles: list[Candle]) -> TradeHypothesis | None:
        if len(candles) < self.h1_slow_period + 1:
            return None
        if self.h4_candles and candles[-1].instrument != self.h4_candles[0].instrument:
            raise ValueError(
                f"h1 candle instrument ({candles[-1].instrument.symbol}) does not match "
                f"h4_candles' instrument ({self.h4_candles[0].instrument.symbol})"
            )

        h1_closes = [(c.bid.close + c.ask.close) / 2 for c in candles]
        h1_fast = _sma_seeded_ema(h1_closes, self.h1_fast_period)
        h1_slow = _sma_seeded_ema(h1_closes, self.h1_slow_period)
        current_diff = h1_fast[-1] - h1_slow[-1]
        previous_diff = h1_fast[-2] - h1_slow[-2]

        if previous_diff <= 0 and current_diff > 0:
            h1_signal = TargetPosition.LONG
        elif previous_diff >= 0 and current_diff < 0:
            h1_signal = TargetPosition.SHORT
        else:
            return None  # no H1 crossover event this bar: nothing to gate

        current_candle = candles[-1]
        h4_visible = [
            c
            for c in self.h4_candles
            if c.is_finalized
            and c.start_time.value.timestamp() + _H4_DURATION_SECONDS
            <= current_candle.start_time.value.timestamp()
        ]
        h4_bias = _h4_bias(h4_visible, self.h4_fast_period, self.h4_slow_period)

        confirmed = (h1_signal is TargetPosition.LONG and h4_bias == "BULLISH") or (
            h1_signal is TargetPosition.SHORT and h4_bias == "BEARISH"
        )

        if confirmed:
            return self._hypothesis(
                current_candle,
                h1_signal,
                f"H1 EMA{self.h1_fast_period}/{self.h1_slow_period} crossed toward "
                f"{h1_signal.value}, confirmed by H4 {h4_bias} bias",
            )
        return self._hypothesis(
            current_candle,
            TargetPosition.FLAT,
            f"H1 EMA{self.h1_fast_period}/{self.h1_slow_period} crossed toward "
            f"{h1_signal.value}, NOT confirmed by H4 (bias={h4_bias}): closing to flat",
        )

    def _hypothesis(
        self, current_candle: Candle, target_position: TargetPosition, rationale: str
    ) -> TradeHypothesis:
        return TradeHypothesis(
            instrument=current_candle.instrument,
            target_position=target_position,
            generated_at=current_candle.start_time,
            timeframe=current_candle.granularity,  # H1: the driving series, not H4
            strategy_key=self.strategy_key,
            strategy_version=self.strategy_version,
            parameters=params_from_dict(
                {
                    "h1_fast_period": self.h1_fast_period,
                    "h1_slow_period": self.h1_slow_period,
                    "h4_fast_period": self.h4_fast_period,
                    "h4_slow_period": self.h4_slow_period,
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


def _h4_bias(h4_candles: list[Candle], fast_period: int, slow_period: int) -> str | None:
    """`"BULLISH"`/`"BEARISH"`/`"NEUTRAL"`, or `None` if there isn't yet
    `slow_period + 1` visible H4 candles to judge it -- treated by the
    caller exactly like `"NEUTRAL"` (unconfirmed), not a special case."""
    if len(h4_candles) < slow_period + 1:
        return None
    h4_closes = [(c.bid.close + c.ask.close) / 2 for c in h4_candles]
    fast = _sma_seeded_ema(h4_closes, fast_period)[-1]
    slow = _sma_seeded_ema(h4_closes, slow_period)[-1]
    if fast > slow:
        return "BULLISH"
    if fast < slow:
        return "BEARISH"
    return "NEUTRAL"
