from dataclasses import dataclass
from decimal import Decimal

from forex_agent.domain._guards import require_decimal
from forex_agent.domain.trade_side import TradeSide


@dataclass(frozen=True, slots=True)
class Price:
    """A bid/ask quote. Both sides are required — CLAUDE.md's backtest rule
    ("Backtests must include spread") depends on never collapsing a quote
    down to a single mid price.
    """

    bid: Decimal
    ask: Decimal

    def __post_init__(self) -> None:
        require_decimal("bid", self.bid)
        require_decimal("ask", self.ask)
        if self.bid <= 0 or self.ask <= 0:
            raise ValueError(f"bid and ask must be positive, got bid={self.bid} ask={self.ask}")
        if self.ask < self.bid:
            raise ValueError(f"ask ({self.ask}) must not be less than bid ({self.bid})")

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / 2

    def entry_price(self, side: TradeSide) -> Decimal:
        """CLAUDE.md: "Long trades: enter at ask. Short trades: enter at bid."""
        return self.ask if side is TradeSide.LONG else self.bid

    def exit_price(self, side: TradeSide) -> Decimal:
        """CLAUDE.md: "Long trades: exit at bid. Short trades: exit at ask."""
        return self.bid if side is TradeSide.LONG else self.ask
