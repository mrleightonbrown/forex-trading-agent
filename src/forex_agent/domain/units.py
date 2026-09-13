from dataclasses import dataclass
from decimal import Decimal

from forex_agent.domain._guards import require_positive_decimal


@dataclass(frozen=True, slots=True)
class Units:
    """A trade/position size, always a positive magnitude.

    Direction is expressed separately via `TradeSide` — encoding it as the
    sign of this value was deliberately avoided, since a sign-based
    direction is easy to lose or flip silently in arithmetic.
    """

    value: Decimal

    def __post_init__(self) -> None:
        require_positive_decimal("value", self.value)
