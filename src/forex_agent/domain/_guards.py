"""Shared validation helpers for domain value objects.

Private to the domain package (leading underscore) — not part of its public
API, just deduplicated `__post_init__` checks.
"""

from decimal import Decimal

from forex_agent.domain.availability_confidence import AvailabilityConfidence
from forex_agent.domain.timestamps import UtcTimestamp


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


def require_revision_sequence(value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"revision_sequence must be an int, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"revision_sequence must not be negative, got {value}")


def require_availability_consistency(
    availability: UtcTimestamp | None, confidence: AvailabilityConfidence
) -> None:
    """FX-51: `availability` must be `None` if and only if `confidence`
    is `AvailabilityConfidence.UNKNOWN` -- shared by every FX-51
    vintage type (`EconomicEventScheduleVintage`/`ConsensusVintage`/
    `ActualValueVintage`) so this invariant cannot drift between them.
    Mirrors `MacroObservationVintage`'s own `released_at_is_verified`/
    `released_at_is_conservative_bound` mutual-exclusivity check
    (FX-44H), generalized for a field that can also be entirely unset
    rather than only ever holding one of two confirmed-timestamp
    flavors.
    """
    if not isinstance(confidence, AvailabilityConfidence):
        raise TypeError(f"confidence must be an AvailabilityConfidence, got {type(confidence)!r}")
    if availability is not None and not isinstance(availability, UtcTimestamp):
        raise TypeError(
            f"availability must be a UtcTimestamp or None, got {type(availability).__name__}"
        )
    if confidence is AvailabilityConfidence.UNKNOWN:
        if availability is not None:
            raise ValueError(
                "availability must be None when confidence is AvailabilityConfidence.UNKNOWN "
                "-- do not invent a timestamp for a genuinely unestablished availability"
            )
    elif availability is None:
        raise ValueError(
            f"availability must not be None when confidence is {confidence} -- "
            "a VERIFIED or ESTIMATED claim requires an actual timestamp"
        )
