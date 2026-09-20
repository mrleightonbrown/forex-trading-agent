"""FX-37: an `IncrementalStrategy` counterpart to
`MultiTimeframeTrendStrategy` (FX-25) -- same `strategy_key`/parameters/
rationale/logic, same strategy, just computed with O(1)-per-bar state
instead of full from-scratch H1/H4 EMA recomputation and H4-visibility
refiltering every call.

`MultiTimeframeTrendStrategy` itself is UNCHANGED and remains the
permanent ground-truth reference this is parity-tested against (see
`tests/unit/domain/strategies/
test_multi_timeframe_trend_incremental.py`).

`IncrementalStrategy.on_candle` only ever receives one stream (the
driving H1 series) -- there's no way to hand it a second, H4 stream
through that same interface. This class keeps the SAME shape the slow
strategy already uses to solve that: the full H4 series is a
constructor argument (legitimate for backtesting, which always
operates over already-fetched historical data), and an internal cursor
advances into it as H1 time progresses, feeding each newly-visible H4
candle into an incremental H4 EMA pair exactly once, in order, the
moment it becomes visible -- rather than refiltering and recomputing
the whole H4 EMA from scratch on every H1 bar.

Visibility uses the same canonical `candle_boundary.candle_end_time`
the slow strategy uses (FX-25H) -- not duplicated, imported directly,
since that function is already the one shared, canonical definition,
not a per-strategy helper. H4 candles are consumed in ascending order
(`h4_candles` is required to be `require_consistent_series` --
strictly ascending), and `candle_end_time` is monotonic in start_time
for a fixed granularity, so once one H4 candle isn't yet visible,
neither is any later one -- the cursor can stop advancing for this
bar without missing anything. A non-finalized H4 candle is permanently
skipped (never fed to the EMA, matching the slow strategy's own
`c.is_finalized` filter) without stopping the cursor from continuing
past it.

A real, easy-to-miss subtlety this class deliberately preserves rather
than "fixing": the slow strategy's own `len(candles) < h1_slow_period +
1: return None` guard, worked through carefully, turns out to be
EXACTLY equivalent to "the H1 EMA doesn't have a second diff value to
compare against yet" -- not a separate, additional gate. That means
granularity/instrument validation is skipped entirely during H1 EMA
warm-up in the slow strategy (it never reaches those checks), and this
class reproduces that by placing its own equivalent checks in the same
relative position -- after the "previous diff not yet available" early
return, not before it -- rather than checking eagerly on every call.
"""

from datetime import datetime
from decimal import Decimal
from typing import ClassVar

from forex_agent.domain.candle import Candle
from forex_agent.domain.candle_boundary import candle_end_time
from forex_agent.domain.candle_series import require_consistent_series
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.incremental_ema import IncrementalSmaSeededEma
from forex_agent.domain.target_position import TargetPosition
from forex_agent.domain.trade_hypothesis import TradeHypothesis, params_from_dict


class IncrementalMultiTimeframeTrendStrategy:
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
        self.reset()

    def reset(self) -> None:
        self._h1_fast_ema = IncrementalSmaSeededEma(self.h1_fast_period)
        self._h1_slow_ema = IncrementalSmaSeededEma(self.h1_slow_period)
        self._h1_previous_diff: Decimal | None = None
        self._h4_fast_ema = IncrementalSmaSeededEma(self.h4_fast_period)
        self._h4_slow_ema = IncrementalSmaSeededEma(self.h4_slow_period)
        self._h4_fast_value: Decimal | None = None
        self._h4_slow_value: Decimal | None = None
        self._h4_cursor = 0
        self._h4_consumed_count = 0

    def _advance_h4(self, up_to: datetime) -> None:
        while self._h4_cursor < len(self.h4_candles):
            h4_candle = self.h4_candles[self._h4_cursor]
            if not h4_candle.is_finalized:
                self._h4_cursor += 1
                continue
            if candle_end_time(h4_candle.start_time.value, Granularity.H4) > up_to:
                break
            h4_close = (h4_candle.bid.close + h4_candle.ask.close) / 2
            fast = self._h4_fast_ema.update(h4_close)
            slow = self._h4_slow_ema.update(h4_close)
            if fast is not None:
                self._h4_fast_value = fast
            if slow is not None:
                self._h4_slow_value = slow
            self._h4_cursor += 1
            self._h4_consumed_count += 1

    def _current_h4_bias(self) -> str | None:
        # Matches the slow strategy's own `_h4_bias` gate exactly: it
        # requires `slow_period + 1` VISIBLE candles -- one more than
        # `_sma_seeded_ema` itself needs to produce a value -- so keying
        # this off EMA readiness alone would fire one candle too early.
        if self._h4_consumed_count < self.h4_slow_period + 1:
            return None
        if self._h4_fast_value is None or self._h4_slow_value is None:
            return None
        if self._h4_fast_value > self._h4_slow_value:
            return "BULLISH"
        if self._h4_fast_value < self._h4_slow_value:
            return "BEARISH"
        return "NEUTRAL"

    def on_candle(self, candle: Candle) -> TradeHypothesis | None:
        close = (candle.bid.close + candle.ask.close) / 2
        fast = self._h1_fast_ema.update(close)
        slow = self._h1_slow_ema.update(close)
        self._advance_h4(candle.start_time.value)

        if fast is None or slow is None:
            return None

        current_diff = fast - slow

        if self._h1_previous_diff is None:
            self._h1_previous_diff = current_diff
            return None

        previous_diff = self._h1_previous_diff
        self._h1_previous_diff = current_diff

        # Matches the slow strategy's own ordering exactly: these checks
        # are unreachable while the H1 EMA doesn't yet have a second diff
        # to compare (the two early returns above) -- see this module's
        # docstring for why that's not a separate, additional gate.
        if candle.granularity is not Granularity.H1:
            raise ValueError(
                f"driving candles must be Granularity.H1, got {candle.granularity} -- "
                "this strategy is explicitly H1/H4; a generic any-timeframe version is a "
                "different, unbuilt strategy"
            )
        if self.h4_candles and candle.instrument != self.h4_candles[0].instrument:
            raise ValueError(
                f"h1 candle instrument ({candle.instrument.symbol}) does not match "
                f"h4_candles' instrument ({self.h4_candles[0].instrument.symbol})"
            )

        if previous_diff <= 0 and current_diff > 0:
            h1_signal = TargetPosition.LONG
        elif previous_diff >= 0 and current_diff < 0:
            h1_signal = TargetPosition.SHORT
        else:
            return None  # no H1 crossover event this bar: nothing to gate

        h4_bias = self._current_h4_bias()
        confirmed = (h1_signal is TargetPosition.LONG and h4_bias == "BULLISH") or (
            h1_signal is TargetPosition.SHORT and h4_bias == "BEARISH"
        )

        if confirmed:
            return self._hypothesis(
                candle,
                h1_signal,
                f"H1 EMA{self.h1_fast_period}/{self.h1_slow_period} crossed toward "
                f"{h1_signal.value}, confirmed by H4 {h4_bias} bias",
            )
        return self._hypothesis(
            candle,
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
            timeframe=current_candle.granularity,
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
