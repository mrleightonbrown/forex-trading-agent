"""FX-47: `IncrementalCloseChannelBreakoutStrategy` golden parity tests
against the slow, ground-truth `CloseChannelBreakoutStrategy`.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from forex_agent.domain.backtest import run_backtest
from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.incremental_strategy import run_backtest_incremental
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.strategies.close_channel_breakout import CloseChannelBreakoutStrategy
from forex_agent.domain.strategies.close_channel_breakout_incremental import (
    IncrementalCloseChannelBreakoutStrategy,
)
from forex_agent.domain.timestamps import UtcTimestamp

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")
_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)

# A varied series with both upward and downward breakouts, so both LONG
# and SHORT decisions are actually exercised, not just one direction.
_CLOSES = [100 + int(30 * __import__("math").sin(i / 9)) + (i % 11) - 5 for i in range(300)]


def _candle(i: int, close: int) -> Candle:
    p = Decimal(close)
    spread = Decimal(1 + (i % 3))
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
    slow = CloseChannelBreakoutStrategy(lookback=5)
    fast = IncrementalCloseChannelBreakoutStrategy(lookback=5)

    slow_hypotheses = run_backtest(slow, _CANDLES)
    fast_hypotheses = run_backtest_incremental(fast, _CANDLES)

    assert len(slow_hypotheses) > 5, "fixture must actually exercise several decisions"
    long_count = sum(1 for h in slow_hypotheses if h.target_position.value == "LONG")
    short_count = sum(1 for h in slow_hypotheses if h.target_position.value == "SHORT")
    assert long_count > 0 and short_count > 0, "fixture must exercise both directions"
    assert slow_hypotheses == fast_hypotheses


def test_incremental_matches_slow_engine_with_default_lookback() -> None:
    slow_hypotheses = run_backtest(CloseChannelBreakoutStrategy(), _CANDLES)
    fast_hypotheses = run_backtest_incremental(IncrementalCloseChannelBreakoutStrategy(), _CANDLES)

    assert slow_hypotheses == fast_hypotheses


def test_incremental_reset_matches_fresh_instance() -> None:
    """FX-29H's own lesson: reusing an instance across two replay calls
    must match a fresh instance's output on the second call, not carry
    state over."""
    fast = IncrementalCloseChannelBreakoutStrategy(lookback=5)
    first = run_backtest_incremental(fast, _CANDLES)
    second = run_backtest_incremental(fast, _CANDLES)

    assert first == second
