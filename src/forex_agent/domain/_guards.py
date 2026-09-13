"""Shared validation helpers for domain value objects.

Private to the domain package (leading underscore) — not part of its public
API, just deduplicated `__post_init__` checks.
"""

from decimal import Decimal


def require_decimal(name: str, value: object) -> None:
    """CLAUDE.md: never use float for prices, balances, units, or P&L."""
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal, got {type(value).__name__}")


def require_positive_decimal(name: str, value: Decimal) -> None:
    require_decimal(name, value)
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value}")


def require_currency_code(name: str, value: str) -> None:
    if not (isinstance(value, str) and len(value) == 3 and value.isalpha() and value.isupper()):
        raise ValueError(f"{name} must be a 3-letter uppercase currency code, got {value!r}")
