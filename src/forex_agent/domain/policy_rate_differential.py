"""FX-45: pair-relative policy-rate differential -- a deterministic
MONETARY-POLICY feature, deliberately never called "carry" anywhere in
this module (FX-45 section 2/15: policy-rate differential is not
tradeable financing return, not an interest-rate strategy, not a
rate-arbitrage signal).

`policy_rate_differential = base_currency_rate - quote_currency_rate`,
Decimal-only, computed separately for each of the two rate semantics
`domain.policy_rate_state` establishes (`ANNOUNCED`/`EFFECTIVE`) --
this module never conflates them; every result type below carries
`rate_semantics` explicitly and full per-leg provenance, so nothing
downstream can mistake one for the other.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from forex_agent.domain._guards import require_decimal
from forex_agent.domain.macro_observation_vintage import MacroObservationVintage
from forex_agent.domain.timestamps import UtcTimestamp


class RateSemantics(Enum):
    """Which of the two policy-rate notions a
    `PolicyRateDifferentialSnapshot`/`PolicyRateDifferentialFeature`
    represents -- see `domain.policy_rate_state`'s own module
    docstring for the full distinction. Never interchangeable."""

    ANNOUNCED = "ANNOUNCED"
    EFFECTIVE = "EFFECTIVE"


class DifferentialDirection(Enum):
    """The sign of a differential CHANGE, defined purely mathematically
    (FX-45 section 8) -- never a fuzzy/thresholded classification.
    `UNCHANGED` is the exact-zero case, not a "near zero" band."""

    WIDENING = "WIDENING"
    NARROWING = "NARROWING"
    UNCHANGED = "UNCHANGED"


@dataclass(frozen=True, slots=True)
class CurrencyRateState:
    """One currency leg's full, auditable provenance for a
    `PolicyRateDifferentialSnapshot` (FX-45 section 7) -- everything a
    reviewer needs to trace `rate` back to the exact stored vintage and
    its own timing-confidence classification, without re-querying
    anything."""

    currency: str
    rate: Decimal
    series_key: str
    observation_period: UtcTimestamp
    revision_sequence: int
    released_at: UtcTimestamp
    effective_at: UtcTimestamp | None
    released_at_is_verified: bool
    released_at_is_conservative_bound: bool

    def __post_init__(self) -> None:
        require_decimal("rate", self.rate)

    @staticmethod
    def from_vintage(currency: str, vintage: MacroObservationVintage) -> "CurrencyRateState":
        return CurrencyRateState(
            currency=currency,
            rate=vintage.value,
            series_key=vintage.series_key,
            observation_period=vintage.observation_period,
            revision_sequence=vintage.revision_sequence,
            released_at=vintage.released_at,
            effective_at=vintage.effective_at,
            released_at_is_verified=vintage.released_at_is_verified,
            released_at_is_conservative_bound=vintage.released_at_is_conservative_bound,
        )


@dataclass(frozen=True, slots=True)
class PolicyRateDifferentialSnapshot:
    """One point-in-time pair-relative policy-rate differential (FX-45
    section 7) -- `differential = base.rate - quote.rate`, `Decimal`
    only. `pair` is the display form `"BASE/QUOTE"` (see `format_pair`)
    -- reversing base/quote reverses the sign (FX-45 section 9); this
    type does not enforce that itself, `rate_differential` does."""

    pair: str
    as_of: UtcTimestamp
    rate_semantics: RateSemantics
    base: CurrencyRateState
    quote: CurrencyRateState
    differential: Decimal

    def __post_init__(self) -> None:
        require_decimal("differential", self.differential)


@dataclass(frozen=True, slots=True)
class PolicyRateDifferentialFeature:
    """FX-45 section 8's deterministic companions to a `current`
    snapshot -- three independently-computed changes, each with its
    own mathematically-defined `DifferentialDirection` (never a single
    overall direction conflating them). Any change FX-45 could not
    defensibly compute (insufficient history for that specific lag) is
    `None`, paired with a `None` direction -- never a guessed value or
    an UNCHANGED default."""

    current: PolicyRateDifferentialSnapshot
    change_since_previous: Decimal | None
    direction_since_previous: DifferentialDirection | None
    change_3m: Decimal | None
    direction_3m: DifferentialDirection | None
    change_6m: Decimal | None
    direction_6m: DifferentialDirection | None


@dataclass(frozen=True, slots=True)
class DifferentialUnavailable:
    """Why FX-45 is deliberately NOT returning a
    `PolicyRateDifferentialFeature` for a requested `(pair, as_of,
    rate_semantics)` -- e.g. a currency with no canonical policy rate
    at all (XAU), or one whose current state lacks the `rate_semantics`
    -specific data needed (e.g. EFFECTIVE requested but the governing
    vintage has no `effective_at`). Distinct from `domain.research_
    readiness.ResearchIntervalNotReadyError`, which is raised (not
    returned) when the underlying DATA exists but is not safe to
    trust -- this type is for cases where safe data may exist but the
    requested semantics/currency combination is structurally
    unsupported."""

    pair: str
    as_of: UtcTimestamp
    rate_semantics: RateSemantics
    reason: str


def format_pair(base_currency: str, quote_currency: str) -> str:
    """The display form FX-45 uses throughout: `"BASE/QUOTE"` (a
    slash, matching this story's own convention -- distinct from
    `domain.instrument.Instrument.symbol`'s underscore-joined broker-
    instrument form, a different concept for a different purpose)."""
    return f"{base_currency}/{quote_currency}"


def rate_differential(base_rate: Decimal, quote_rate: Decimal) -> Decimal:
    """`base_rate - quote_rate`, `Decimal` only (FX-45 section 2/9).

    Reversing the arguments reverses the sign by construction --
    `rate_differential(a, b) == -rate_differential(b, a)` always holds
    for `Decimal` subtraction; FX-45's own orientation test proves this
    at the point where a snapshot is actually built (base/quote
    assignment, not this arithmetic), since `Decimal` subtraction
    itself cannot silently break this invariant.
    """
    require_decimal("base_rate", base_rate)
    require_decimal("quote_rate", quote_rate)
    return base_rate - quote_rate


def _state_timestamp(
    state: CurrencyRateState, rate_semantics: RateSemantics
) -> UtcTimestamp | None:
    if rate_semantics is RateSemantics.ANNOUNCED:
        return state.released_at
    return state.effective_at


def pair_differential_change_since_previous(
    current_differential: Decimal,
    rate_semantics: RateSemantics,
    current_base: CurrencyRateState,
    current_quote: CurrencyRateState,
    previous_base: CurrencyRateState | None,
    previous_quote: CurrencyRateState | None,
) -> Decimal | None:
    """ "Change since previous policy observation" (FX-45 section 8):
    `current_differential` minus the pair differential as it stood
    immediately before the MORE RECENT of the two legs' current states
    took hold.

    Only the leg that actually moved most recently is "reverted" to
    its own previous state -- the other leg's CURRENT rate is kept,
    since it did not change at that instant. If both legs' current
    states began at the exact same instant (a tie), both are reverted.
    `None` (never a guess) if the mover's own previous state is
    unavailable, or if `rate_semantics` is `EFFECTIVE` and either
    current state's `effective_at` is unexpectedly absent (should not
    happen given `domain.policy_rate_state.effective_state_as_of`'s
    own guarantee, but this function never assumes it).
    """
    base_ts = _state_timestamp(current_base, rate_semantics)
    quote_ts = _state_timestamp(current_quote, rate_semantics)
    if base_ts is None or quote_ts is None:
        return None

    if base_ts.value > quote_ts.value:
        previous_differential = (
            None
            if previous_base is None
            else rate_differential(previous_base.rate, current_quote.rate)
        )
    elif quote_ts.value > base_ts.value:
        previous_differential = (
            None
            if previous_quote is None
            else rate_differential(current_base.rate, previous_quote.rate)
        )
    else:
        previous_differential = (
            None
            if previous_base is None or previous_quote is None
            else rate_differential(previous_base.rate, previous_quote.rate)
        )

    if previous_differential is None:
        return None
    return current_differential - previous_differential


def classify_direction(change: Decimal | None) -> DifferentialDirection | None:
    """`WIDENING` for a positive change, `NARROWING` for a negative
    one, `UNCHANGED` for exactly zero -- `None` in, `None` out (FX-45
    section 8: no fuzzy "neutral" band; an unavailable change stays
    unavailable, it is never coerced into `UNCHANGED`)."""
    if change is None:
        return None
    require_decimal("change", change)
    if change > 0:
        return DifferentialDirection.WIDENING
    if change < 0:
        return DifferentialDirection.NARROWING
    return DifferentialDirection.UNCHANGED
