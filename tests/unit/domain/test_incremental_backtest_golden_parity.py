"""FX-29: golden parity tests at the `SimulatedTrade` level -- the exact
acceptance criterion: "On small datasets, produce exactly identical
hypotheses and trades to the existing slow run_backtest + simulate_trades
... Add golden parity tests comparing old and new engines trade-for-trade:
side, entry time/price, exit time/price, P&L."

The per-strategy test files (`test_ema_crossover_incremental.py`,
`test_ema_crossover_trend_regime_gated_incremental.py`) already prove
hypothesis-level parity, which trivially implies trade-level parity once
fed through the same, unmodified `simulate_trades` -- this file checks
that explicitly anyway, at the exact granularity the acceptance
criterion names, rather than leaving it as an implication.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from forex_agent.domain.backtest import run_backtest
from forex_agent.domain.candle import Candle
from forex_agent.domain.granularity import Granularity
from forex_agent.domain.incremental_strategy import run_backtest_incremental
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.money import Money
from forex_agent.domain.ohlc import Ohlc
from forex_agent.domain.simulated_trade import SimulatedTrade
from forex_agent.domain.strategies.ema_crossover import EmaCrossoverStrategy
from forex_agent.domain.strategies.ema_crossover_incremental import (
    IncrementalEmaCrossoverStrategy,
)
from forex_agent.domain.strategies.ema_crossover_trend_regime_gated import (
    EmaCrossoverTrendRegimeGatedStrategy,
)
from forex_agent.domain.strategies.ema_crossover_trend_regime_gated_incremental import (
    IncrementalEmaCrossoverTrendRegimeGatedStrategy,
)
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trade_side import TradeSide
from forex_agent.domain.trade_simulation import simulate_trades

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")
_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)

_TREND_SEGMENT = [100 + int(30 * __import__("math").sin(i / 7)) + (i % 5) for i in range(200)]
_CHOPPY_SEGMENT = [100 + (5 if i % 2 == 0 else -5) for i in range(100)]
_CLOSES = _TREND_SEGMENT + _CHOPPY_SEGMENT + _TREND_SEGMENT


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


_CANDLES = [_candle(i, c) for i, c in enumerate(_CLOSES)]


_Fingerprint = tuple[TradeSide, UtcTimestamp, Decimal, UtcTimestamp, Decimal, Money]


def _fingerprints(trades: list[SimulatedTrade]) -> list[_Fingerprint]:
    return [(t.side, t.entry_time, t.entry_price, t.exit_time, t.exit_price, t.pnl) for t in trades]


def test_ema_crossover_golden_parity() -> None:
    slow_trades = simulate_trades(
        run_backtest(EmaCrossoverStrategy(fast_period=5, slow_period=13), _CANDLES), _CANDLES
    )
    fast_trades = simulate_trades(
        run_backtest_incremental(
            IncrementalEmaCrossoverStrategy(fast_period=5, slow_period=13), _CANDLES
        ),
        _CANDLES,
    )

    assert len(slow_trades) > 5, "fixture must actually exercise several trades"
    assert _fingerprints(slow_trades) == _fingerprints(fast_trades)


def test_ema_crossover_trend_regime_gated_golden_parity() -> None:
    slow_trades = simulate_trades(
        run_backtest(
            EmaCrossoverTrendRegimeGatedStrategy(
                fast_period=5, slow_period=13, regime_period=7, regime_threshold=Decimal("25")
            ),
            _CANDLES,
        ),
        _CANDLES,
    )
    fast_trades = simulate_trades(
        run_backtest_incremental(
            IncrementalEmaCrossoverTrendRegimeGatedStrategy(
                fast_period=5, slow_period=13, regime_period=7, regime_threshold=Decimal("25")
            ),
            _CANDLES,
        ),
        _CANDLES,
    )

    assert len(slow_trades) > 5, "fixture must actually exercise several trades"
    assert _fingerprints(slow_trades) == _fingerprints(fast_trades)
