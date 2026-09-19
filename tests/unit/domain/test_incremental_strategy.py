"""FX-29H: `run_backtest_incremental`'s lifecycle guarantees -- found by
external review, independently reproduced before fixing (see
docs/DECISIONS.md). Uses `IncrementalEmaCrossoverStrategy` as the test
vehicle (a real `IncrementalStrategy`, not a purpose-built double) since
the bug is about `run_backtest_incremental`'s own driving logic, not
anything strategy-specific.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.incremental_strategy import run_backtest_incremental
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.strategies.ema_crossover_incremental import (
    IncrementalEmaCrossoverStrategy,
)
from forex_agent.domain.timestamps import UtcTimestamp

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")
_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)
_CLOSES = [100 + int(30 * __import__("math").sin(i / 7)) + (i % 5) for i in range(100)]


def _candle(i: int, close: int, *, is_finalized: bool = True) -> Candle:
    p = Decimal(close)
    flat = Ohlc(open=p, high=p, low=p, close=p)
    return Candle(
        instrument=EUR_USD,
        granularity=Granularity.H1,
        start_time=UtcTimestamp(_EPOCH + timedelta(hours=i)),
        bid=flat,
        ask=flat,
        volume=1,
        is_finalized=is_finalized,
    )


_CANDLES = [_candle(i, c) for i, c in enumerate(_CLOSES)]


def test_reusing_the_same_strategy_instance_produces_identical_results() -> None:
    """The exact scenario external review reproduced: without a reset,
    a second call on the same (stateful) instance silently diverged from
    the first, because EMA state carried over."""
    strategy = IncrementalEmaCrossoverStrategy(fast_period=5, slow_period=13)

    first = run_backtest_incremental(strategy, _CANDLES)
    second = run_backtest_incremental(strategy, _CANDLES)

    assert first, "fixture must actually produce hypotheses"
    assert first == second


def test_reused_instance_matches_a_fresh_instance() -> None:
    reused = IncrementalEmaCrossoverStrategy(fast_period=5, slow_period=13)
    run_backtest_incremental(reused, _CANDLES)  # "warm" it with a prior call
    reused_result = run_backtest_incremental(reused, _CANDLES)

    fresh = IncrementalEmaCrossoverStrategy(fast_period=5, slow_period=13)
    fresh_result = run_backtest_incremental(fresh, _CANDLES)

    assert reused_result == fresh_result


def test_a_failed_validation_leaves_no_partially_consumed_strategy_state() -> None:
    """The other half of external review's reproduction: a non-finalized
    candle partway through a series used to raise only after the
    strategy had already processed (and mutated its state on) every
    preceding candle. Candles are now validated in full before any
    on_candle() call, so a rejected series leaves the strategy exactly
    as it was -- a subsequent correct call on the SAME instance must
    match a fresh instance's output."""
    poisoned = [*_CANDLES[:30], _candle(30, _CLOSES[30], is_finalized=False)]
    strategy = IncrementalEmaCrossoverStrategy(fast_period=5, slow_period=13)

    with pytest.raises(ValueError, match="not finalized"):
        run_backtest_incremental(strategy, poisoned)

    corrected_result = run_backtest_incremental(strategy, _CANDLES)

    fresh = IncrementalEmaCrossoverStrategy(fast_period=5, slow_period=13)
    fresh_result = run_backtest_incremental(fresh, _CANDLES)

    assert corrected_result == fresh_result


def test_validation_failure_happens_before_reset_is_even_needed() -> None:
    """A stronger structural check than the above: prove the strategy's
    state genuinely never advances past the first mutation attempt for
    a rejected series -- not just that a later correct call happens to
    self-correct via reset()."""
    poisoned = [*_CANDLES[:5], _candle(5, _CLOSES[5], is_finalized=False)]
    strategy = IncrementalEmaCrossoverStrategy(fast_period=5, slow_period=13)

    with pytest.raises(ValueError, match="not finalized"):
        run_backtest_incremental(strategy, poisoned)

    # slow_period=13 needs 13 candles before the first EMA value exists;
    # if validation had let any on_candle() calls through before raising,
    # this internal buffer would be partially filled. Reaching into
    # "private" state here is deliberate: it's the only way to prove
    # *zero* mutation happened, not just that a later reset() papers
    # over whatever did.
    assert strategy._fast_ema._seed_buffer == []
    assert strategy._slow_ema._seed_buffer == []
