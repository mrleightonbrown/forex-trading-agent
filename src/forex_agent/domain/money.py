from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from forex_agent.domain._guards import require_currency_code, require_decimal


@dataclass(frozen=True, slots=True)
class Money:
    """A balance/P&L amount in a specific currency.

    CLAUDE.md: never use float for balances or P&L. Arithmetic across
    different currencies is rejected rather than silently mixed — converting
    between currencies is an application/infrastructure concern (needs an
    exchange rate), not something this value object should do implicitly.
    """

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        require_decimal("amount", self.amount)
        require_currency_code("currency", self.currency)

    def __add__(self, other: Any) -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Any) -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        return Money(self.amount - other.amount, self.currency)

    def _require_same_currency(self, other: "Money") -> None:
        if other.currency != self.currency:
            raise ValueError(
                f"cannot combine Money in different currencies: {self.currency} vs {other.currency}"
            )
