"""FX-36: `IncrementalVolatilityExpansionBreakoutStrategy` golden parity
tests against the slow, ground-truth `VolatilityExpansionBreakoutStrategy`.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from forex_agent.domain.backtest import run_backtest
from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.incremental_strategy import run_backtest_incremental
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.strategies.volatility_expansion import (
    VolatilityExpansionBreakoutStrategy,
)
from forex_agent.domain.strategies.volatility_expansion_incremental import (
    IncrementalVolatilityExpansionBreakoutStrategy,
)
from forex_agent.domain.target_position import TargetPosition
from forex_agent.domain.timestamps import UtcTimestamp

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")
_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)

# A long, varied series with both calm and volatile stretches, so the
# ATR-expansion gate genuinely toggles on and off, not just one regime.
_CLOSES = [
    100 + int(30 * __import__("math").sin(i / 11)) + (i % 7) * (3 if (i // 50) % 2 else 1)
    for i in range(400)
]


def _candle(i: int, close: int) -> Candle:
    p = Decimal(close)
    spread = Decimal(2 + (i % 5))  # varying range, not a flat candle
    flat = Ohlc(open=p, high=p + spread, low=p - spread, close=p)
    return Candle(
        instrument=EUR_USD,
        granularity=Granularity.H1,
        start_time=UtcTimestamp(_EPOCH + timedelta(hours=i)),
        bid=flat,
        ask=flat,
        volume=1,
        is_finalized=True,
    )


_CANDLES = [_candle(i, c) for i, c in enumerate(_CLOSES)]


def test_incremental_matches_slow_engine_exactly() -> None:
    slow = VolatilityExpansionBreakoutStrategy(
        short_period=3, long_period=7, breakout_lookback=5, expansion_threshold=Decimal("1.2")
    )
    fast = IncrementalVolatilityExpansionBreakoutStrategy(
        short_period=3, long_period=7, breakout_lookback=5, expansion_threshold=Decimal("1.2")
    )

    slow_hypotheses = run_backtest(slow, _CANDLES)
    fast_hypotheses = run_backtest_incremental(fast, _CANDLES)

    assert len(slow_hypotheses) > 5, "fixture must actually exercise several decisions"
    flat_count = sum(1 for h in slow_hypotheses if h.target_position.value == "FLAT")
    assert flat_count > 0, "fixture must actually exercise a FLAT exit"
    assert slow_hypotheses == fast_hypotheses


def test_incremental_matches_slow_engine_with_default_periods() -> None:
    slow_hypotheses = run_backtest(VolatilityExpansionBreakoutStrategy(), _CANDLES)
    fast_hypotheses = run_backtest_incremental(
        IncrementalVolatilityExpansionBreakoutStrategy(), _CANDLES
    )

    assert slow_hypotheses == fast_hypotheses


def test_incremental_matches_slow_engine_when_breakout_lookback_exceeds_long_period() -> None:
    """The specific edge case this strategy's own docstring flags:
    breakout_lookback > long_period means ATR can become ready before
    the Donchian window fills -- exercises the combined readiness gate,
    not just ATR readiness alone."""
    slow = VolatilityExpansionBreakoutStrategy(
        short_period=2, long_period=4, breakout_lookback=9, expansion_threshold=Decimal("1.2")
    )
    fast = IncrementalVolatilityExpansionBreakoutStrategy(
        short_period=2, long_period=4, breakout_lookback=9, expansion_threshold=Decimal("1.2")
    )
    slow_hypotheses = run_backtest(slow, _CANDLES)
    fast_hypotheses = run_backtest_incremental(fast, _CANDLES)

    assert slow_hypotheses == fast_hypotheses


def test_strategy_key_matches_the_slow_strategy() -> None:
    assert (
        IncrementalVolatilityExpansionBreakoutStrategy.strategy_key
        == VolatilityExpansionBreakoutStrategy.strategy_key
    )


def test_expansion_gate_is_inclusive_at_the_exact_threshold() -> None:
    """A real gap the parity tests above don't close: their synthetic
    series never happens to produce an ATR ratio EXACTLY equal to
    `expansion_threshold`, so a `>` vs `>=` bug in the gate comparison
    passed every parity test above undetected (confirmed directly: I
    injected exactly that bug and all of them still passed). Decimal
    arithmetic can land exactly on a boundary (unlike float), and the
    slow strategy's own gate is `>=` -- this constructs a hand-verified
    series (via IncrementalWilderAtr directly, not guessed) where the
    ATR ratio is EXACTLY 1.5 at the decision bar, with short_period=1/
    long_period=2 chosen specifically because short_period=1 makes the
    short ATR exactly equal the raw True Range, keeping the arithmetic
    traceable by hand.
    """
    short_period, long_period, breakout_lookback = 1, 2, 1
    threshold = Decimal("1.5")

    def _bar(i: int, high: int, low: int, close: int) -> Candle:
        h, lo, c = Decimal(high), Decimal(low), Decimal(close)
        flat = Ohlc(open=c, high=h, low=lo, close=c)
        return Candle(
            instrument=EUR_USD,
            granularity=Granularity.H1,
            start_time=UtcTimestamp(_EPOCH + timedelta(hours=i)),
            bid=flat,
            ask=flat,
            volume=1,
            is_finalized=True,
        )

    # Hand-verified via IncrementalWilderAtr directly before writing this
    # test: True Range sequence 4, 4, 12 (each bar's own high-low range
    # dominates, decoupling TR from prev_close complexity) gives
    # short_atr=12 (period=1: always the latest TR), long_atr=8 (period=2
    # Wilder-smoothed: seed=(4+4)/2=4, then (4+12)/2=8) at bar 3 --
    # ratio = 12/8 = 1.5 EXACTLY. bar3's close (110) also breaks above
    # bar2's high (106), the 1-bar Donchian window -- so whether the gate
    # is inclusive determines whether a LONG hypothesis fires at all.
    candles = [
        _bar(0, 101, 99, 100),
        _bar(1, 104, 100, 102),
        _bar(2, 106, 102, 104),
        _bar(3, 116, 104, 110),
    ]

    slow = VolatilityExpansionBreakoutStrategy(
        short_period=short_period,
        long_period=long_period,
        breakout_lookback=breakout_lookback,
        expansion_threshold=threshold,
    )
    fast = IncrementalVolatilityExpansionBreakoutStrategy(
        short_period=short_period,
        long_period=long_period,
        breakout_lookback=breakout_lookback,
        expansion_threshold=threshold,
    )

    slow_hypothesis = slow.evaluate(candles)
    fast_hypothesis = run_backtest_incremental(fast, candles)[-1] if candles else None

    assert slow_hypothesis is not None
    boundary_message = "the slow strategy's own >= gate must fire exactly at the boundary"
    assert slow_hypothesis.target_position is TargetPosition.LONG, boundary_message
    assert fast_hypothesis == slow_hypothesis
