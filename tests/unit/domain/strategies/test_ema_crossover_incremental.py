"""FX-29: `IncrementalEmaCrossoverStrategy` golden parity tests against
the slow, ground-truth `EmaCrossoverStrategy` -- the acceptance
criterion is exact agreement, not "close enough", checked at every
decision point (via `run_backtest`/`run_backtest_incremental` over the
same series), not just in an aggregated trade list.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from forex_agent.domain.backtest import run_backtest
from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.incremental_strategy import run_backtest_incremental
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.strategies.ema_crossover import EmaCrossoverStrategy
from forex_agent.domain.strategies.ema_crossover_incremental import (
    IncrementalEmaCrossoverStrategy,
)
from forex_agent.domain.timestamps import UtcTimestamp

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")
_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)

# A long, varied, non-monotonic synthetic series -- many crossovers of
# both directions, not just one clean trend.
_CLOSES = [100 + int(30 * __import__("math").sin(i / 7)) + (i % 5) for i in range(400)]


def _candle(i: int, close: int) -> Candle:
    p = Decimal(close)
    flat = Ohlc(open=p, high=p, low=p, close=p)
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
    slow_hypotheses = run_backtest(EmaCrossoverStrategy(fast_period=5, slow_period=13), _CANDLES)
    fast_hypotheses = run_backtest_incremental(
        IncrementalEmaCrossoverStrategy(fast_period=5, slow_period=13), _CANDLES
    )

    assert len(slow_hypotheses) > 5, "fixture must actually exercise several crossovers"
    assert slow_hypotheses == fast_hypotheses


def test_incremental_matches_slow_engine_with_default_periods() -> None:
    slow_hypotheses = run_backtest(EmaCrossoverStrategy(), _CANDLES)
    fast_hypotheses = run_backtest_incremental(IncrementalEmaCrossoverStrategy(), _CANDLES)

    assert slow_hypotheses == fast_hypotheses


def test_strategy_key_matches_the_slow_strategy() -> None:
    assert IncrementalEmaCrossoverStrategy.strategy_key == EmaCrossoverStrategy.strategy_key
