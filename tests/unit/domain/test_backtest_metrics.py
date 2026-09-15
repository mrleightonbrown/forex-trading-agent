"""FX-17: backtest metrics tests.

The reference trade set below (pnl = [10, -5, 15, -10, 20, 0] USD) is
cross-checked against an independent reference calculation for every
field, including Sharpe/Sortino/max-drawdown — not just qualitative
correctness.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_agent.domain.backtest_metrics import compute_metrics
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.money import Money
from forex_agent.domain.simulated_trade import SimulatedTrade
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trade_side import TradeSide

EUR_USD = Instrument(base_currency="EUR", quote_currency="USD")
GBP_EUR = Instrument(base_currency="GBP", quote_currency="EUR")


def _ts(minute: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, 0, minute, 0, tzinfo=UTC))


def _trade(minute: int, pnl: str, side: TradeSide = TradeSide.LONG) -> SimulatedTrade:
    return SimulatedTrade(
        instrument=EUR_USD,
        side=side,
        entry_price=Decimal("1.1000"),
        entry_time=_ts(minute),
        exit_price=Decimal("1.1010"),
        exit_time=_ts(minute + 1),
        pnl=Money(Decimal(pnl), "USD"),
    )


# Reference set: pnl = [10, -5, 15, -10, 20, 0], exit-time-ordered.
_REFERENCE_TRADES = [
    _trade(0, "10"),
    _trade(1, "-5"),
    _trade(2, "15"),
    _trade(3, "-10"),
    _trade(4, "20"),
    _trade(5, "0"),
]


def test_rejects_empty_trade_list() -> None:
    with pytest.raises(ValueError, match="empty"):
        compute_metrics([])


def test_rejects_mixed_currency_trades() -> None:
    # SimulatedTrade itself already enforces pnl.currency ==
    # instrument.quote_currency, so a mixed-currency list can only
    # legitimately arise from trades on different instruments.
    gbp_eur_trade = SimulatedTrade(
        instrument=GBP_EUR,
        side=TradeSide.LONG,
        entry_price=Decimal("1.1"),
        entry_time=_ts(1),
        exit_price=Decimal("1.1"),
        exit_time=_ts(2),
        pnl=Money(Decimal("5"), "EUR"),
    )
    trades = [_trade(0, "10"), gbp_eur_trade]

    with pytest.raises(ValueError, match="currency"):
        compute_metrics(trades)


def test_trade_and_outcome_counts() -> None:
    metrics = compute_metrics(_REFERENCE_TRADES)

    assert metrics.trade_count == 6
    assert metrics.win_count == 3
    assert metrics.loss_count == 2
    assert metrics.breakeven_count == 1


def test_win_rate() -> None:
    metrics = compute_metrics(_REFERENCE_TRADES)

    assert metrics.win_rate == Decimal("0.5")


def test_average_win_and_loss() -> None:
    metrics = compute_metrics(_REFERENCE_TRADES)

    assert metrics.average_win == Money(Decimal("15"), "USD")
    assert metrics.average_loss == Money(Decimal("-7.5"), "USD")


def test_average_win_is_none_when_no_wins() -> None:
    metrics = compute_metrics([_trade(0, "-5"), _trade(1, "-10")])

    assert metrics.average_win is None
    assert metrics.average_loss == Money(Decimal("-7.5"), "USD")


def test_average_loss_is_none_when_no_losses() -> None:
    metrics = compute_metrics([_trade(0, "5"), _trade(1, "10")])

    assert metrics.average_loss is None
    assert metrics.average_win == Money(Decimal("7.5"), "USD")


def test_total_pnl_and_expectancy() -> None:
    metrics = compute_metrics(_REFERENCE_TRADES)

    assert metrics.total_pnl == Money(Decimal("30"), "USD")
    assert metrics.expectancy == Money(Decimal("5"), "USD")


def test_profit_factor() -> None:
    metrics = compute_metrics(_REFERENCE_TRADES)

    assert metrics.profit_factor == Decimal("3")


def test_profit_factor_is_none_with_no_losses() -> None:
    metrics = compute_metrics([_trade(0, "5"), _trade(1, "10")])

    assert metrics.profit_factor is None


def test_max_drawdown() -> None:
    metrics = compute_metrics(_REFERENCE_TRADES)

    # cumulative: 10, 5, 20, 10, 30, 30 -> largest peak-to-trough is
    # 10 (peak) -> 5 (trough) after the second trade.
    assert metrics.max_drawdown == Money(Decimal("10"), "USD")


def test_max_drawdown_is_zero_when_equity_never_declines() -> None:
    metrics = compute_metrics([_trade(0, "5"), _trade(1, "10")])

    assert metrics.max_drawdown == Money(Decimal("0"), "USD")


def test_max_drawdown_is_order_independent_of_input_list_order() -> None:
    # Same trades, shuffled input order - max_drawdown must still be
    # computed by exit_time, not input order.
    shuffled = [_REFERENCE_TRADES[i] for i in [4, 0, 5, 2, 1, 3]]

    metrics = compute_metrics(shuffled)

    assert metrics.max_drawdown == Money(Decimal("10"), "USD")


def test_sharpe_matches_independent_reference() -> None:
    metrics = compute_metrics(_REFERENCE_TRADES)

    assert metrics.sharpe is not None
    assert metrics.sharpe.quantize(Decimal("0.000001")) == Decimal("0.422577")


def test_sortino_matches_independent_reference() -> None:
    metrics = compute_metrics(_REFERENCE_TRADES)

    assert metrics.sortino is not None
    assert metrics.sortino.quantize(Decimal("0.000001")) == Decimal("1.095445")


def test_sharpe_is_none_with_a_single_trade() -> None:
    metrics = compute_metrics([_trade(0, "10")])

    assert metrics.sharpe is None


def test_sharpe_is_none_with_zero_variance() -> None:
    metrics = compute_metrics([_trade(0, "10"), _trade(1, "10")])

    assert metrics.sharpe is None


def test_sortino_is_none_with_no_downside() -> None:
    metrics = compute_metrics([_trade(0, "5"), _trade(1, "10")])

    assert metrics.sortino is None


# --- composable segmentation, per the FX-17 design decision -----------------


def test_segmentation_by_filtering_before_calling() -> None:
    trades = [
        _trade(0, "10", side=TradeSide.LONG),
        _trade(1, "-5", side=TradeSide.SHORT),
        _trade(2, "20", side=TradeSide.LONG),
    ]

    long_only = [t for t in trades if t.side is TradeSide.LONG]
    long_metrics = compute_metrics(long_only)

    assert long_metrics.trade_count == 2
    assert long_metrics.total_pnl == Money(Decimal("30"), "USD")
    # The full, unfiltered set still reflects all three trades.
    assert compute_metrics(trades).trade_count == 3
