from dataclasses import dataclass

from forex_agent.domain._guards import require_currency_code
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class DeclaredPolicyRateGap:
    """An explicitly declared, intentional absence of a canonical
    policy-rate definition for one currency over `[start, end)` (FX-42H.1).

    FX-42H allowed `policy_rate_registry.validate_registry` to accept ANY
    gap between two consecutive `PolicyRateDefinition`s for a currency,
    reasoning that a currency can have a period with no comparable
    canonical scalar at all (the Bank of Japan's quantity-target eras).
    That blanket tolerance was too permissive: it could not distinguish a
    genuinely intentional gap from an accidental one (a typo in a
    boundary date, a forgotten definition) -- both would silently pass.
    FX-42H.1 replaces it with this type: every gap between consecutive
    definitions must now be explicitly declared, with WHY it exists
    (`reason`), or registry validation fails. See
    `policy_rate_registry.validate_registry`.

    Half-open, like `PolicyRateDefinition`'s own `valid_from`/`valid_to`:
    `start` is inclusive, `end` is exclusive. Unlike `PolicyRateDefinition.
    valid_to`, `end` is required (not optional) -- an intentional gap is,
    by definition, eventually followed by renewed coverage; an
    open-ended "we stopped defining this currency" is not a gap, it is
    simply the registry not (yet) extending that far, which needs no
    declaration.

    Fields:
        currency: the ISO 4217 currency this gap applies to, matching a
            `MacroSeriesDefinition.currency` in the registry.
        start: when the gap begins (inclusive) -- must equal the
            `valid_to` of the definition immediately preceding it.
        end: when the gap ends (exclusive) -- must equal the
            `valid_from` of the definition immediately following it.
        reason: non-empty, human-readable explanation of why no
            canonical scalar exists for this window (e.g. "BoJ's
            operating target was a quantity, not a rate, during this
            window").
    """

    currency: str
    start: UtcTimestamp
    end: UtcTimestamp
    reason: str

    def __post_init__(self) -> None:
        require_currency_code("currency", self.currency)
        if not isinstance(self.start, UtcTimestamp):
            raise TypeError(f"start must be a UtcTimestamp, got {type(self.start)!r}")
        if not isinstance(self.end, UtcTimestamp):
            raise TypeError(f"end must be a UtcTimestamp, got {type(self.end)!r}")
        if self.end.value <= self.start.value:
            raise ValueError(
                f"end ({self.end.value.isoformat()}) must be after "
                f"start ({self.start.value.isoformat()})"
            )
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError(f"reason must be a non-empty string, got {self.reason!r}")

    def covers(self, as_of: UtcTimestamp) -> bool:
        """Whether `as_of` falls within this gap: `start <= as_of < end`."""
        return self.start.value <= as_of.value < self.end.value
