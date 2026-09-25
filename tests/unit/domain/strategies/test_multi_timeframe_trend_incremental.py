"""FX-37: `IncrementalMultiTimeframeTrendStrategy` golden parity tests
against the slow, ground-truth `MultiTimeframeTrendStrategy`.
"""

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TypedDict

from forex_agent.domain.backtest import run_backtest
from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.incremental_strategy import run_backtest_incremental
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.strategies.multi_timeframe_trend import MultiTimeframeTrendStrategy
from forex_agent.domain.strategies.multi_timeframe_trend_incremental import (
    IncrementalMultiTimeframeTrendStrategy,
)
from forex_agent.domain.target_position import TargetPosition
from forex_agent.domain.timestamps import UtcTimestamp

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")
_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


class _PeriodKwargs(TypedDict):
    """Precise key/value types for the `**kwargs`-unpacked period overrides
    below -- a plain `dict[str, int]` would let mypy treat `**kwargs` as
    potentially supplying an int to `strategy_version: str` too, since it
    can't rule out that key being present in a generically-typed dict."""

    h1_fast_period: int
    h1_slow_period: int
    h4_fast_period: int
    h4_slow_period: int


# The exact hand-derived series from test_multi_timeframe_trend.py's own
# module docstring -- reused verbatim so its known decision trace (LONG at
# hour 19, FLAT at 22, LONG at 26, SHORT at 32) doubles as a parity check.
_H1_CLOSES = [100] * 16 + [
    100,
    100,
    100,
    110,
    120,
    130,
    100,
    90,
    80,
    90,
    100,
    110,
    120,
    130,
    140,
    150,
    100,
    90,
    80,
]
_H4_CLOSES = [100, 102, 104, 106, 108, 110, 105, 95, 85, 75, 70, 65]


def _h1_ts(hour: int) -> UtcTimestamp:
    return UtcTimestamp(_EPOCH + timedelta(hours=hour))


def _flat_candle(
    start: UtcTimestamp,
    granularity: Granularity,
    price: int,
    instrument: Instrument = EUR_USD,
) -> Candle:
    p = Decimal(price)
    flat = Ohlc(open=p, high=p, low=p, close=p)
    return Candle(
        instrument=instrument,
        granularity=granularity,
        start_time=start,
        bid=flat,
        ask=flat,
        volume=1,
        is_finalized=True,
    )


def _h1_candles() -> list[Candle]:
    return [_flat_candle(_h1_ts(h), Granularity.H1, _H1_CLOSES[h]) for h in range(len(_H1_CLOSES))]


def _h4_candles(closes: list[int] = _H4_CLOSES) -> list[Candle]:
    return [_flat_candle(_h1_ts(4 * k), Granularity.H4, closes[k]) for k in range(len(closes))]


def test_incremental_matches_slow_engine_exactly() -> None:
    slow = MultiTimeframeTrendStrategy(
        h4_candles=_h4_candles(),
        h1_fast_period=2,
        h1_slow_period=3,
        h4_fast_period=2,
        h4_slow_period=3,
    )
    fast = IncrementalMultiTimeframeTrendStrategy(
        h4_candles=_h4_candles(),
        h1_fast_period=2,
        h1_slow_period=3,
        h4_fast_period=2,
        h4_slow_period=3,
    )
    candles = _h1_candles()

    slow_hypotheses = run_backtest(slow, candles)
    fast_hypotheses = run_backtest_incremental(fast, candles)

    assert [(h.target_position, h.generated_at) for h in slow_hypotheses] == [
        (TargetPosition.LONG, _h1_ts(19)),
        (TargetPosition.FLAT, _h1_ts(22)),
        (TargetPosition.LONG, _h1_ts(26)),
        (TargetPosition.SHORT, _h1_ts(32)),
    ], "fixture's own known trace must still hold -- otherwise this isn't testing what it claims"
    assert slow_hypotheses == fast_hypotheses


def test_incremental_matches_slow_engine_with_default_periods() -> None:
    # Independent sine-based series (different frequencies for H1 vs H4,
    # like FX-36's own synthetic fixture) so both confirmed and
    # unconfirmed (FLAT) decisions actually occur, not just one path.
    h1_closes = [100 + int(30 * math.sin(i / 11)) + (i % 7) for i in range(400)]
    h4_closes = [100 + int(25 * math.sin(i / 7)) + (i % 5) for i in range(100)]
    h1_candles = [_flat_candle(_h1_ts(i), Granularity.H1, c) for i, c in enumerate(h1_closes)]
    h4_candles = _h4_candles(h4_closes)

    slow = MultiTimeframeTrendStrategy(h4_candles=h4_candles)
    fast = IncrementalMultiTimeframeTrendStrategy(h4_candles=h4_candles)

    slow_hypotheses = run_backtest(slow, h1_candles)
    fast_hypotheses = run_backtest_incremental(fast, h1_candles)

    assert len(slow_hypotheses) > 3, "fixture must actually exercise several decisions"
    confirmed = [h for h in slow_hypotheses if h.target_position is not TargetPosition.FLAT]
    flat = [h for h in slow_hypotheses if h.target_position is TargetPosition.FLAT]
    assert confirmed, "fixture must exercise at least one confirmed decision"
    assert flat, "fixture must exercise at least one unconfirmed (FLAT) decision"
    assert slow_hypotheses == fast_hypotheses


def test_strategy_key_matches_the_slow_strategy() -> None:
    assert (
        IncrementalMultiTimeframeTrendStrategy.strategy_key
        == MultiTimeframeTrendStrategy.strategy_key
    )


def test_incremental_matches_slow_engine_across_dst_fall_back_transition() -> None:
    """Reuses FX-25H's own regression fixture verbatim: an H4 candle
    starting 2026-11-01T05:00Z (fall-back day) actually closes at
    10:00Z (5 real hours), not the naive fixed-duration 09:00Z. Both
    engines must agree, and must agree on the SPECIFIC known trace, not
    just agree on some arbitrary answer."""
    background = [
        _flat_candle(UtcTimestamp(datetime(2026, 10, 31, 21, 0, tzinfo=UTC)), Granularity.H4, 100),
        _flat_candle(UtcTimestamp(datetime(2026, 11, 1, 1, 0, tzinfo=UTC)), Granularity.H4, 100),
    ]
    fall_back_candle = _flat_candle(
        UtcTimestamp(datetime(2026, 11, 1, 5, 0, tzinfo=UTC)), Granularity.H4, 200
    )
    h4_candles = [*background, fall_back_candle]

    def _h1_crossover_ending_at(hour: int) -> list[Candle]:
        base = datetime(2026, 11, 1, hour - 3, 0, tzinfo=UTC)
        closes = [100, 100, 100, 110]
        return [
            _flat_candle(UtcTimestamp(base + timedelta(hours=i)), Granularity.H1, closes[i])
            for i in range(4)
        ]

    kwargs: _PeriodKwargs = {
        "h1_fast_period": 2,
        "h1_slow_period": 3,
        "h4_fast_period": 1,
        "h4_slow_period": 2,
    }
    slow_not_yet = MultiTimeframeTrendStrategy(h4_candles=h4_candles, **kwargs)
    fast_not_yet = IncrementalMultiTimeframeTrendStrategy(h4_candles=h4_candles, **kwargs)
    not_yet_candles = _h1_crossover_ending_at(9)

    slow_not_yet_result = slow_not_yet.evaluate(not_yet_candles)
    fast_not_yet_result = run_backtest_incremental(fast_not_yet, not_yet_candles)[-1]

    assert slow_not_yet_result is not None
    assert slow_not_yet_result.target_position is TargetPosition.FLAT
    assert fast_not_yet_result == slow_not_yet_result

    slow_visible = MultiTimeframeTrendStrategy(h4_candles=h4_candles, **kwargs)
    fast_visible = IncrementalMultiTimeframeTrendStrategy(h4_candles=h4_candles, **kwargs)
    visible_candles = _h1_crossover_ending_at(10)

    slow_visible_result = slow_visible.evaluate(visible_candles)
    fast_visible_result = run_backtest_incremental(fast_visible, visible_candles)[-1]

    assert slow_visible_result is not None
    assert slow_visible_result.target_position is TargetPosition.LONG
    assert fast_visible_result == slow_visible_result


def test_h4_bias_requires_one_more_visible_candle_than_ema_readiness() -> None:
    """A real gap that agreeing on the FX-25 fixture alone wouldn't have
    caught: the slow strategy's own `_h4_bias` requires `slow_period + 1`
    VISIBLE H4 candles, one more than `_sma_seeded_ema` itself needs to
    produce a value. An incremental H4 EMA tracker naturally becomes
    "ready" one candle earlier than that. h4_slow_period=2 here, so the
    boundary is exactly 2 visible candles (EMA-ready, but the slow
    strategy still requires 3) vs 3 (both ready) -- confirmed this
    actually catches a real bug: I temporarily removed the incremental
    engine's extra `_h4_consumed_count` gate and watched this test fail
    (a bias got computed one candle early) while every other parity test
    above still passed, then restored the gate and confirmed this test
    passes again.
    """
    kwargs: _PeriodKwargs = {
        "h1_fast_period": 2,
        "h1_slow_period": 3,
        "h4_fast_period": 1,
        "h4_slow_period": 2,
    }
    # Only 2 H4 candles closed by the H1 decision bar -- one short of the
    # 3 the slow strategy's own gate requires. Wildly bullish closes so a
    # premature bias read would clearly diverge (LONG) from the correct,
    # unconfirmed read (FLAT).
    h4_candles = [
        _flat_candle(_h1_ts(0), Granularity.H4, 100),
        _flat_candle(_h1_ts(4), Granularity.H4, 200),
    ]
    h1_candles = [
        _flat_candle(_h1_ts(h), Granularity.H1, c)
        for h, c in enumerate([100, 100, 100, 110], start=8)
    ]

    slow = MultiTimeframeTrendStrategy(h4_candles=h4_candles, **kwargs)
    fast = IncrementalMultiTimeframeTrendStrategy(h4_candles=h4_candles, **kwargs)

    slow_result = slow.evaluate(h1_candles)
    fast_result = run_backtest_incremental(fast, h1_candles)[-1]

    assert slow_result is not None
    boundary_message = "only 2 of the required 3 visible H4 candles: bias must be unconfirmed"
    assert slow_result.target_position is TargetPosition.FLAT, boundary_message
    assert fast_result == slow_result
