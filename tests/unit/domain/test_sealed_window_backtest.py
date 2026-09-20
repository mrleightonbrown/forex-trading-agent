"""FX-38H: `run_sealed_window_backtest` tests -- the economically-sealed
evaluation-window primitive used to rerun FX-38's holdout/development
comparison without boundary-straddling leakage.
"""

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from forex_agent.domain.backtest import run_backtest
from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.incremental_strategy import run_backtest_incremental
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.sealed_window_backtest import run_sealed_window_backtest
from forex_agent.domain.strategies.ema_crossover import EmaCrossoverStrategy
from forex_agent.domain.strategies.ema_crossover_incremental import (
    IncrementalEmaCrossoverStrategy,
)
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trade_simulation import simulate_trades

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")
_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)

# 400 candles: comfortably more than fast_period=5/slow_period=13's own
# warm-up needs, with enough oscillation (sine-based, like every other
# strategy fixture in this codebase) to produce several crossovers both
# before and after any reasonable split point.
_CLOSES = [100 + int(20 * math.sin(i / 9)) + (i % 5) for i in range(400)]


def _candle(i: int, close: int) -> Candle:
    p = Decimal(close)
    flat = Ohlc(open=p, high=p + Decimal("1"), low=p - Decimal("1"), close=p)
    return Candle(
        instrument=EUR_USD,
        granularity=Granularity.H1,
        start_time=UtcTimestamp(_EPOCH + timedelta(hours=i)),
        bid=flat,
        ask=flat,
        volume=1,
        is_finalized=True,
    )


_ALL_CANDLES = [_candle(i, c) for i, c in enumerate(_CLOSES)]
_WARMUP = _ALL_CANDLES[:200]
_WINDOW = _ALL_CANDLES[200:]

# A second split, confirmed directly (before writing the force-close test
# below, not assumed) to produce exactly one trade that would straddle
# the window boundary in a continuous run: entry at candle 278 (inside
# [150, 300)), exit at candle 306 (outside it) -- see
# test_force_closes_at_the_windows_own_last_candle_not_beyond.
_WARMUP_MID = _ALL_CANDLES[:150]
_WINDOW_MID = _ALL_CANDLES[150:300]


def _run(strategy: IncrementalEmaCrossoverStrategy):
    return lambda candles: run_backtest_incremental(strategy, candles)


def test_sealed_hypotheses_never_precede_window_start() -> None:
    sealed = run_sealed_window_backtest(
        _run(IncrementalEmaCrossoverStrategy(fast_period=5, slow_period=13)), _WARMUP, _WINDOW
    )

    assert sealed, "fixture must actually produce hypotheses in the window"
    window_start = _WINDOW[0].start_time.value
    assert all(h.generated_at.value >= window_start for h in sealed)


def test_sealed_hypotheses_match_the_continuous_run_within_the_window() -> None:
    """Sealing must not change WHICH hypotheses fire within the window,
    only drop the ones from before it -- the strategy's own decisions,
    warmed up correctly, are unchanged."""
    strategy = IncrementalEmaCrossoverStrategy(fast_period=5, slow_period=13)
    continuous = run_backtest_incremental(strategy, _ALL_CANDLES)
    window_start = _WINDOW[0].start_time.value
    expected_in_window = [h for h in continuous if h.generated_at.value >= window_start]

    sealed = run_sealed_window_backtest(
        _run(IncrementalEmaCrossoverStrategy(fast_period=5, slow_period=13)), _WARMUP, _WINDOW
    )

    assert sealed == expected_in_window


def test_warmup_actually_matters_not_a_no_op() -> None:
    """Without warm-up, the strategy cold-starts on window_candles alone:
    its own EMA state is seeded fresh at the window boundary rather than
    carrying real prior momentum, so its crossover EVENTS occur at
    genuinely different bars than the warmed-up version's -- NOT simply
    "the same events, shifted later in time" (a crossover's timing
    depends on the whole recent EMA trajectory, not just readiness).
    What IS strictly guaranteed, and checked directly rather than
    assumed: cold start cannot produce ANY hypothesis before it has seen
    its own slow_period+1 candles (`IncrementalSmaSeededEma` needs
    `period` candles to seed, then one more for a second diff to compare
    against) -- and, empirically, this fixture's cold vs. warm hypothesis
    lists genuinely differ, confirming warm-up isn't a no-op."""
    slow_period = 13
    with_warmup = run_sealed_window_backtest(
        _run(IncrementalEmaCrossoverStrategy(fast_period=5, slow_period=slow_period)),
        _WARMUP,
        _WINDOW,
    )
    without_warmup = run_sealed_window_backtest(
        _run(IncrementalEmaCrossoverStrategy(fast_period=5, slow_period=slow_period)),
        [],
        _WINDOW,
    )

    assert with_warmup, "fixture must produce at least one warmed-up hypothesis"
    assert without_warmup, "fixture must produce at least one cold-start hypothesis too"
    assert with_warmup != without_warmup, "warm-up must change which hypotheses fire"

    # The cold-start version cannot fire before it has slow_period+1 of
    # its own bars -- a hard lower bound, not a heuristic.
    minimum_cold_start_index = slow_period  # 0-indexed: the (slow_period+1)-th candle
    first_without_warmup = without_warmup[0].generated_at.value
    assert first_without_warmup >= _WINDOW[minimum_cold_start_index].start_time.value


def test_portfolio_starts_flat_at_window_boundary() -> None:
    """The full pipeline -- sealed hypotheses fed to simulate_trades
    alongside ONLY window_candles -- must never produce a trade whose
    entry_time precedes the window. A position implied by warm-up-only
    hypotheses must never appear as an already-open trade."""
    sealed = run_sealed_window_backtest(
        _run(IncrementalEmaCrossoverStrategy(fast_period=5, slow_period=13)), _WARMUP, _WINDOW
    )

    trades = simulate_trades(sealed, _WINDOW)

    assert trades, "fixture must produce at least one trade in the window"
    window_start = _WINDOW[0].start_time.value
    window_end = _WINDOW[-1].start_time.value
    for trade in trades:
        assert trade.entry_time.value >= window_start
        assert trade.entry_time.value <= window_end
        assert trade.exit_time.value >= window_start
        assert trade.exit_time.value <= window_end


def test_force_closes_at_the_windows_own_last_candle_not_beyond() -> None:
    """A position still open when window_candles run out is force-closed
    at window_candles[-1]'s close, DIFFERING from what a continuous run
    over the full history does with that same trade -- confirmed
    directly (not assumed): a continuous run over the full 400-candle
    fixture opens a LONG at candle 278 and doesn't close it until
    candle 306, execution price from candle 306's open. Candle 306 is
    outside the [150, 300) window used here, so the sealed version MUST
    force-close at candle 299 (the window's own last candle) instead --
    a different exit_time and a different exit price, not a coincidence."""
    continuous_strategy = IncrementalEmaCrossoverStrategy(fast_period=5, slow_period=13)
    continuous_trades = simulate_trades(
        run_backtest_incremental(continuous_strategy, _ALL_CANDLES), _ALL_CANDLES
    )
    window_end = _WINDOW_MID[-1].start_time.value
    straddling = [
        t
        for t in continuous_trades
        if t.entry_time.value <= window_end and t.exit_time.value > window_end
    ]
    assert len(straddling) == 1, "fixture's own confirmed boundary-straddling trade must exist"
    continuous_exit_time = straddling[0].exit_time.value
    continuous_exit_price = straddling[0].exit_price

    sealed = run_sealed_window_backtest(
        _run(IncrementalEmaCrossoverStrategy(fast_period=5, slow_period=13)),
        _WARMUP_MID,
        _WINDOW_MID,
    )
    sealed_trades = simulate_trades(sealed, _WINDOW_MID)

    assert sealed_trades
    sealed_last_trade = sealed_trades[-1]
    assert (
        sealed_last_trade.exit_time.value == window_end
    ), "must force-close exactly at the window's own last candle"
    assert sealed_last_trade.exit_time.value < continuous_exit_time
    assert sealed_last_trade.exit_price != continuous_exit_price


def test_rejects_empty_window_candles() -> None:
    with pytest.raises(ValueError, match="window_candles"):
        run_sealed_window_backtest(
            _run(IncrementalEmaCrossoverStrategy(fast_period=5, slow_period=13)), _WARMUP, []
        )


def test_rejects_warmup_and_window_out_of_order() -> None:
    reversed_warmup = list(reversed(_WARMUP))
    with pytest.raises(ValueError):
        run_sealed_window_backtest(
            _run(IncrementalEmaCrossoverStrategy(fast_period=5, slow_period=13)),
            reversed_warmup,
            _WINDOW,
        )


def test_works_with_the_slow_reference_engine_too() -> None:
    """`run` is a plain callable -- `run_backtest` (slow) composes exactly
    the same way as `run_backtest_incremental`, needed for strategies
    without an incremental engine (e.g. CloseChannelBreakoutStrategy)."""
    strategy = EmaCrossoverStrategy(fast_period=5, slow_period=13)
    sealed = run_sealed_window_backtest(
        lambda candles: run_backtest(strategy, candles), _WARMUP, _WINDOW
    )

    assert sealed
    window_start = _WINDOW[0].start_time.value
    assert all(h.generated_at.value >= window_start for h in sealed)
