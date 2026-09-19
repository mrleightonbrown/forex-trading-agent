"""FX-28: EMA-crossover-gated-by-TrendRegime strategy tests.

`fast_period=2, slow_period=3, regime_period=3` (needs 6 candles for
`classify_regime`) throughout -- matching `multi_timeframe_trend.py`'s
own tests' minimal-period convention.

The expected TRENDING/RANGING classifications below were confirmed
directly by running the already-independently-verified `classify_regime`
(FX-12) against each candidate series -- not hand-derived ADX arithmetic.
This mirrors FX-21's replay test precedent: "reuses FX-12's own
already-verified ... fixtures ... rather than re-deriving ADX
arithmetic — its job is bucketing [here: gating], not classification."

- Confirmed LONG: 10 flat bars (100), then a steady climb (+10/bar).
  First crossover at index 10 (close=110); by then ADX is already high
  enough (period=3 adapts fast) to read TRENDING.
- Confirmed SHORT: mirror image, a steady decline.
- Gated FLAT on RANGING: a choppy 105/95 oscillation -- every bar is a
  crossover event, and ADX stays low (RANGING) throughout.
- Gated FLAT on insufficient regime history: [100,100,100,110], a
  crossover at index 3 with only 4 candles (< 2*regime_period=6).
- None on no crossover event: any bar with no new crossover.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from forex_agent.domain.backtest import run_backtest
from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.money import Money
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.regime_segmentation import segment_trades_by_regime
from forex_agent.domain.simulated_trade import SimulatedTrade
from forex_agent.domain.strategies.ema_crossover import EmaCrossoverStrategy
from forex_agent.domain.strategies.ema_crossover_trend_regime_gated import (
    EmaCrossoverTrendRegimeGatedStrategy,
)
from forex_agent.domain.target_position import TargetPosition
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trade_simulation import simulate_trades

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")
_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


def _ts(hour: int) -> UtcTimestamp:
    return UtcTimestamp(_EPOCH + timedelta(hours=hour))


def _flat_candle(hour: int, price: int) -> Candle:
    p = Decimal(price)
    flat = Ohlc(open=p, high=p, low=p, close=p)
    return Candle(
        instrument=EUR_USD,
        granularity=Granularity.H1,
        start_time=_ts(hour),
        bid=flat,
        ask=flat,
        volume=1,
        is_finalized=True,
    )


def _candles(closes: list[int]) -> list[Candle]:
    return [_flat_candle(i, c) for i, c in enumerate(closes)]


def _strategy(**overrides: object) -> EmaCrossoverTrendRegimeGatedStrategy:
    params: dict[str, object] = {
        "fast_period": 2,
        "slow_period": 3,
        "regime_period": 3,
    }
    params.update(overrides)
    return EmaCrossoverTrendRegimeGatedStrategy(**params)  # type: ignore[arg-type]


_CLIMB = [100] * 10 + [100 + 10 * k for k in range(1, 21)]
_DECLINE = [100] * 10 + [100 - 10 * k for k in range(1, 21)]
_CHOPPY = [100 + (5 if i % 2 == 0 else -5) for i in range(30)]


# --- constructor validation -------------------------------------------------


def test_default_parameters() -> None:
    strategy = EmaCrossoverTrendRegimeGatedStrategy()

    assert strategy.fast_period == 20
    assert strategy.slow_period == 50
    assert strategy.regime_period == 14
    assert strategy.regime_threshold == Decimal("25")
    assert strategy.strategy_version == "1"


def test_strategy_key_is_a_class_constant() -> None:
    assert (
        EmaCrossoverTrendRegimeGatedStrategy.strategy_key == "ema_crossover_trend_regime_gated_v1"
    )


def test_rejects_fast_period_not_less_than_slow_period() -> None:
    with pytest.raises(ValueError, match="fast_period"):
        EmaCrossoverTrendRegimeGatedStrategy(fast_period=50, slow_period=50)


def test_rejects_bool_fast_period() -> None:
    with pytest.raises(TypeError, match="fast_period"):
        EmaCrossoverTrendRegimeGatedStrategy(fast_period=True)


def test_rejects_regime_period_below_one() -> None:
    with pytest.raises(ValueError, match="regime_period"):
        EmaCrossoverTrendRegimeGatedStrategy(regime_period=0)


def test_rejects_bool_regime_period() -> None:
    with pytest.raises(TypeError, match="regime_period"):
        EmaCrossoverTrendRegimeGatedStrategy(regime_period=True)


def test_rejects_float_regime_threshold() -> None:
    with pytest.raises(TypeError, match="regime_threshold"):
        EmaCrossoverTrendRegimeGatedStrategy(regime_threshold=25.0)  # type: ignore[arg-type]


def test_rejects_regime_threshold_out_of_range() -> None:
    with pytest.raises(ValueError, match="regime_threshold"):
        EmaCrossoverTrendRegimeGatedStrategy(regime_threshold=Decimal("101"))


# --- evaluate(): confirmed signals -------------------------------------


def test_confirmed_long_when_trending() -> None:
    strategy = _strategy()
    candles = _candles(_CLIMB[:11])  # through index 10, the LONG crossover

    hypothesis = strategy.evaluate(candles)

    assert hypothesis is not None
    assert hypothesis.target_position is TargetPosition.LONG
    assert hypothesis.instrument == EUR_USD
    assert hypothesis.generated_at == _ts(10)
    assert hypothesis.strategy_key == "ema_crossover_trend_regime_gated_v1"
    assert "confirmed by TrendRegime.TRENDING" in hypothesis.rationale


def test_confirmed_short_when_trending() -> None:
    strategy = _strategy()
    candles = _candles(_DECLINE[:11])  # through index 10, the SHORT crossover

    hypothesis = strategy.evaluate(candles)

    assert hypothesis is not None
    assert hypothesis.target_position is TargetPosition.SHORT
    assert hypothesis.generated_at == _ts(10)
    assert "confirmed by TrendRegime.TRENDING" in hypothesis.rationale


# --- evaluate(): gated to FLAT -------------------------------------------


def test_gated_flat_on_ranging_long_signal() -> None:
    strategy = _strategy()
    candles = _candles(_CHOPPY[:7])  # through index 6: LONG crossover, RANGING

    hypothesis = strategy.evaluate(candles)

    assert hypothesis is not None
    assert hypothesis.target_position is TargetPosition.FLAT
    assert hypothesis.generated_at == _ts(6)
    assert "NOT confirmed" in hypothesis.rationale
    assert "RANGING" in hypothesis.rationale


def test_gated_flat_on_ranging_short_signal() -> None:
    strategy = _strategy()
    candles = _candles(_CHOPPY[:8])  # through index 7: SHORT crossover, RANGING

    hypothesis = strategy.evaluate(candles)

    assert hypothesis is not None
    assert hypothesis.target_position is TargetPosition.FLAT
    assert hypothesis.generated_at == _ts(7)


def test_gated_flat_on_insufficient_regime_history() -> None:
    strategy = _strategy()
    candles = _candles([100, 100, 100, 110])  # LONG crossover, only 4 candles (< 6)

    hypothesis = strategy.evaluate(candles)

    assert hypothesis is not None
    assert hypothesis.target_position is TargetPosition.FLAT
    assert "NOT confirmed" in hypothesis.rationale
    assert "regime=None" in hypothesis.rationale


# --- evaluate(): None -----------------------------------------------------


def test_returns_none_with_no_crossover() -> None:
    strategy = _strategy()
    # Index 11: still riding the same LONG cross from index 10, no new event.
    candles = _candles(_CLIMB[:12])

    assert strategy.evaluate(candles) is None


def test_returns_none_with_insufficient_ema_history() -> None:
    strategy = _strategy()
    candles = _candles([100, 100])  # slow_period=3 needs 4 candles

    assert strategy.evaluate(candles) is None


# --- structural equivalence to entry-regime attribution -------------------


def test_gated_trades_exactly_equal_the_trending_attribution_bucket() -> None:
    """A proven structural property, discovered empirically while running
    FX-28's real-data comparison (every instrument's "gated" metrics came
    back numerically IDENTICAL to its "TRENDING-only attribution" metrics
    -- confirmed trade-by-trade before trusting it, not just in aggregate)
    and then verified mathematically: because `EmaCrossoverStrategy` never
    self-emits FLAT (every crossover event is a direction reversal), and
    this strategy's gate uses the exact same regime classification at the
    exact same decision bars `segment_trades_by_regime` already uses, a
    gated position's exit always lands at the same next-event bar an
    unconditional reversal would have closed it at anyway -- so "gated,
    confirmed" trades and "unconditional trades entered during TRENDING"
    are entry/exit/P&L-identical, not just similarly distributed.

    This is a real finding about *this specific pairing*, not a general
    law of regime-gating -- FX-25's H4 confirmation gate (external
    information, a second timeframe) is NOT reducible to attribution the
    same way. Locked in here as a regression: if a future change to
    either strategy's crossover logic ever breaks this equivalence, this
    test should catch it.
    """
    # _DECLINE truncated to stay positive (Ohlc rejects prices <= 0) --
    # the full fixture's tail reaches 0 and below, which is fine for its
    # own standalone use (only the first crossover, at index 10, is ever
    # read there) but not for a full concatenated series like this one.
    combined = _CLIMB + _CHOPPY + _DECLINE[:15]
    candles = _candles(combined)

    unconditional = EmaCrossoverStrategy(fast_period=2, slow_period=3)
    uncond_trades = simulate_trades(run_backtest(unconditional, candles), candles)
    segmented = segment_trades_by_regime(uncond_trades, candles, period=3, threshold=Decimal("25"))
    assert segmented.trending, "fixture must actually exercise the TRENDING bucket"

    gated_trades = simulate_trades(run_backtest(_strategy(), candles), candles)
    assert gated_trades, "fixture must actually produce gated trades"

    def _fingerprint(trades: list[SimulatedTrade]) -> set[tuple[UtcTimestamp, UtcTimestamp, Money]]:
        return {(t.entry_time, t.exit_time, t.pnl) for t in trades}

    assert _fingerprint(gated_trades) == _fingerprint(segmented.trending)
