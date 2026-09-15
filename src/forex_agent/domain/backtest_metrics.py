"""FX-17: the scoreboard. Descriptive statistics for a list of
`SimulatedTrade` — the metric wishlist a growing strategy suite needs
before comparing strategies means anything more than eyeballing P&L.

Deliberately composable, not a grouping engine: `compute_metrics` takes
any `list[SimulatedTrade]` and reports full stats for exactly that list.
"Long vs short" is filtering by `side` and calling this twice; a later
"trending vs ranging" comparison (regime-conditioned experiments) is
filtering by an external regime classification and calling this twice;
year/quarter is filtering by `entry_time`. This function never needs to
know about timeframes or regimes — it does, however (FX-21H.1), require
every trade to share one `instrument`: `pnl` is per-unit notional
(no position sizing yet), so a pip on `EUR_USD` and a pip on `GBP_USD`
aren't economically comparable even though both happen to be USD-quoted.

`sharpe`/`sortino` are explicitly NOT true annualized percentage-return
ratios. `SimulatedTrade.pnl` is per-unit notional (no position sizing
exists yet — see FX-11's docs/DECISIONS.md entry), and trades occur at
irregular intervals with no clean annualization period. These are
computed directly on raw per-trade `Money` P&L (mean / sample standard
deviation, same formula shape as conventional Sharpe/Sortino) — useful
for *relative* comparison between strategies on the same instrument and
timeframe, misleading if read as a directly comparable industry-standard
figure.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from forex_agent.domain.money import Money
from forex_agent.domain.simulated_trade import SimulatedTrade


@dataclass(frozen=True, slots=True)
class BacktestMetrics:
    trade_count: int
    win_count: int
    loss_count: int
    breakeven_count: int
    win_rate: Decimal
    average_win: Money | None
    average_loss: Money | None
    expectancy: Money
    profit_factor: Decimal | None
    total_pnl: Money
    max_drawdown: Money
    sharpe: Decimal | None
    sortino: Decimal | None


def compute_metrics(trades: list[SimulatedTrade]) -> BacktestMetrics:
    """Raises `ValueError` if `trades` is empty (a report on zero trades is
    meaningless, not a valid degenerate case) or spans more than one
    `instrument` (FX-21H.1).

    `instrument`, not merely P&L currency, is the required invariant:
    `Instrument` is a plain value type, and `SimulatedTrade` already
    enforces `pnl.currency == instrument.quote_currency`, so one
    instrument implies one currency automatically — checking currency
    separately would only ever be reachable in a scenario this
    invariant already rules out. Two different instruments sharing one
    quote currency (e.g. `EUR_USD` and `GBP_USD`, both USD) are
    correctly rejected here even though a currency-only check would
    have let them through.
    """
    if not trades:
        raise ValueError("cannot compute metrics for an empty trade list")

    instrument = trades[0].instrument
    for trade in trades:
        if trade.instrument != instrument:
            raise ValueError(
                "all trades must share one instrument; found "
                f"{trade.instrument.symbol!r} and {instrument.symbol!r}"
            )
    currency = instrument.quote_currency

    trade_count = len(trades)
    wins = [t for t in trades if t.pnl.amount > 0]
    losses = [t for t in trades if t.pnl.amount < 0]
    breakeven_count = trade_count - len(wins) - len(losses)

    win_rate = Decimal(len(wins)) / Decimal(trade_count)
    average_win = Money(_mean(t.pnl.amount for t in wins), currency) if wins else None
    average_loss = Money(_mean(t.pnl.amount for t in losses), currency) if losses else None

    total_pnl_amount = _sum(t.pnl.amount for t in trades)
    total_pnl = Money(total_pnl_amount, currency)
    expectancy = Money(total_pnl_amount / trade_count, currency)

    gross_profit = _sum(t.pnl.amount for t in wins)
    gross_loss = -_sum(t.pnl.amount for t in losses)  # positive magnitude
    profit_factor = gross_profit / gross_loss if gross_loss != 0 else None

    mean_pnl = total_pnl_amount / trade_count
    return BacktestMetrics(
        trade_count=trade_count,
        win_count=len(wins),
        loss_count=len(losses),
        breakeven_count=breakeven_count,
        win_rate=win_rate,
        average_win=average_win,
        average_loss=average_loss,
        expectancy=expectancy,
        profit_factor=profit_factor,
        total_pnl=total_pnl,
        max_drawdown=Money(_max_drawdown(trades), currency),
        sharpe=_sharpe(trades, mean_pnl),
        sortino=_sortino(trades, mean_pnl),
    )


def _sum(values: Iterable[Decimal]) -> Decimal:
    return sum(values, Decimal(0))


def _mean(values: Iterable[Decimal]) -> Decimal:
    items = list(values)
    return _sum(items) / len(items)


def _max_drawdown(trades: list[SimulatedTrade]) -> Decimal:
    """Largest peak-to-trough decline in the exit-time-ordered cumulative
    P&L, as a non-negative Decimal (0 if the equity curve never
    declines)."""
    ordered = sorted(trades, key=lambda t: t.exit_time.value)
    cumulative = Decimal(0)
    peak = Decimal(0)
    max_dd = Decimal(0)
    for trade in ordered:
        cumulative += trade.pnl.amount
        peak = max(peak, cumulative)
        max_dd = max(max_dd, peak - cumulative)
    return max_dd


def _sharpe(trades: list[SimulatedTrade], mean_pnl: Decimal) -> Decimal | None:
    """`None` with fewer than 2 trades (sample standard deviation is
    undefined) or zero variance."""
    if len(trades) < 2:
        return None
    variance = _sum((t.pnl.amount - mean_pnl) ** 2 for t in trades) / (len(trades) - 1)
    if variance == 0:
        return None
    return mean_pnl / variance.sqrt()


def _sortino(trades: list[SimulatedTrade], mean_pnl: Decimal) -> Decimal | None:
    """`None` when downside deviation is zero (no trade below the zero
    minimum-acceptable-return line)."""
    downside_variance = _sum(min(Decimal(0), t.pnl.amount) ** 2 for t in trades) / len(trades)
    if downside_variance == 0:
        return None
    return mean_pnl / downside_variance.sqrt()
