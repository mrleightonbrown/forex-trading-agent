from dataclasses import dataclass
from decimal import Decimal

from forex_agent.domain._guards import require_decimal
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.money import Money
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.domain.trade_side import TradeSide


@dataclass(frozen=True, slots=True)
class SimulatedTrade:
    """One simulated round-trip trade from a backtest (FX-11).

    `pnl` is the raw price delta in the quote currency — P&L per single
    unit of base-currency notional, not multiplied by any position size.
    Position sizing is a Risk Engine concern that doesn't exist yet;
    deliberately not invented here.
    """

    instrument: Instrument
    side: TradeSide
    entry_price: Decimal
    entry_time: UtcTimestamp
    exit_price: Decimal
    exit_time: UtcTimestamp
    pnl: Money

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, Instrument):
            raise TypeError(
                f"instrument must be an Instrument, got {type(self.instrument).__name__}"
            )
        if not isinstance(self.side, TradeSide):
            raise TypeError(f"side must be a TradeSide, got {type(self.side).__name__}")
        require_decimal("entry_price", self.entry_price)
        require_decimal("exit_price", self.exit_price)
        if not isinstance(self.entry_time, UtcTimestamp):
            raise TypeError(
                f"entry_time must be a UtcTimestamp, got {type(self.entry_time).__name__}"
            )
        if not isinstance(self.exit_time, UtcTimestamp):
            raise TypeError(
                f"exit_time must be a UtcTimestamp, got {type(self.exit_time).__name__}"
            )
        if not isinstance(self.pnl, Money):
            raise TypeError(f"pnl must be Money, got {type(self.pnl).__name__}")
        if self.exit_time.value < self.entry_time.value:
            raise ValueError("exit_time must not be before entry_time")
        if self.pnl.currency != self.instrument.quote_currency:
            raise ValueError(
                f"pnl currency ({self.pnl.currency}) must match instrument's quote "
                f"currency ({self.instrument.quote_currency})"
            )
