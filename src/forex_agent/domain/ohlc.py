from dataclasses import dataclass
from decimal import Decimal

from forex_agent.domain._guards import require_positive_decimal


@dataclass(frozen=True, slots=True)
class Ohlc:
    """Open/high/low/close for one side (bid or ask) of a candle.

    `Candle` holds one of these per side rather than a single mid-price
    OHLC — CLAUDE.md: "Backtests must include spread."
    """

    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal

    def __post_init__(self) -> None:
        require_positive_decimal("open", self.open)
        require_positive_decimal("high", self.high)
        require_positive_decimal("low", self.low)
        require_positive_decimal("close", self.close)

        actual_max = max(self.open, self.high, self.low, self.close)
        actual_min = min(self.open, self.high, self.low, self.close)
        if self.high != actual_max:
            raise ValueError(
                f"high ({self.high}) must be the maximum of open/high/low/close, "
                f"got max={actual_max}"
            )
        if self.low != actual_min:
            raise ValueError(
                f"low ({self.low}) must be the minimum of open/high/low/close, got min={actual_min}"
            )
