"""FX-29: `IncrementalEmaCrossoverTrendRegimeGatedStrategy` golden parity
tests against the slow, ground-truth `EmaCrossoverTrendRegimeGatedStrategy`.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from forex_agent.domain.backtest import run_backtest
from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.incremental_strategy import run_backtest_incremental
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.strategies.ema_crossover_trend_regime_gated import (
    EmaCrossoverTrendRegimeGatedStrategy,
)
from forex_agent.domain.strategies.ema_crossover_trend_regime_gated_incremental import (
    IncrementalEmaCrossoverTrendRegimeGatedStrategy,
)
from forex_agent.domain.timestamps import UtcTimestamp

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")
_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)

_TREND_SEGMENT = [100 + int(30 * __import__("math").sin(i / 7)) + (i % 5) for i in range(200)]
_CHOPPY_SEGMENT = [100 + (5 if i % 2 == 0 else -5) for i in range(100)]
_CLOSES = _TREND_SEGMENT + _CHOPPY_SEGMENT + _TREND_SEGMENT


def _candle(i: int, close: int) -> Candle:
    p = Decimal(close)
    # High/low spread so the ADX/DM math isn't degenerate (flat candles).
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


_CANDLES = [_candle(i, c) for i, c in enumerate(_CLOSES)]


def test_incremental_matches_slow_engine_exactly() -> None:
    slow = EmaCrossoverTrendRegimeGatedStrategy(
        fast_period=5, slow_period=13, regime_period=7, regime_threshold=Decimal("25")
    )
    fast = IncrementalEmaCrossoverTrendRegimeGatedStrategy(
        fast_period=5, slow_period=13, regime_period=7, regime_threshold=Decimal("25")
    )

    slow_hypotheses = run_backtest(slow, _CANDLES)
    fast_hypotheses = run_backtest_incremental(fast, _CANDLES)

    assert len(slow_hypotheses) > 5, "fixture must actually exercise several decisions"
    gated_flat_count = sum(1 for h in slow_hypotheses if h.rationale.endswith("closing to flat"))
    assert gated_flat_count > 0, "fixture must actually exercise a gated-FLAT outcome"
    assert slow_hypotheses == fast_hypotheses


def test_incremental_matches_slow_engine_with_default_periods() -> None:
    slow_hypotheses = run_backtest(EmaCrossoverTrendRegimeGatedStrategy(), _CANDLES)
    fast_hypotheses = run_backtest_incremental(
        IncrementalEmaCrossoverTrendRegimeGatedStrategy(), _CANDLES
    )

    assert slow_hypotheses == fast_hypotheses


def test_strategy_key_matches_the_slow_strategy() -> None:
    assert (
        IncrementalEmaCrossoverTrendRegimeGatedStrategy.strategy_key
        == EmaCrossoverTrendRegimeGatedStrategy.strategy_key
    )
