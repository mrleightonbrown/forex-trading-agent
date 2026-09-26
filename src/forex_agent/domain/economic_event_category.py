from enum import Enum


class EconomicEventCategory(Enum):
    """The kind of scheduled economic event an `EconomicIndicatorDefinition`
    describes (FX-51).

    Deliberately a small, closed set matching exactly what FX-51's own
    story names as in-scope examples -- not a general economic-event
    taxonomy, the same discipline `domain.macro_category.MacroCategory`
    already established for continuous macro series (FX-41). Extending
    this enum later is cheap precisely because nothing in the domain
    model branches on a specific category value.

    Deliberately NOT reused from `MacroCategory`: a macro series (a
    continuously observed time series like the policy rate itself) and
    a scheduled economic EVENT (a discrete, PIT-sensitive release with
    its own schedule/consensus/actual-value lifecycle) are materially
    different concepts even when they describe the same underlying
    economic subject -- CLAUDE.md's own instruction not to force
    materially different lifecycles into one abstraction, applied here
    in reverse: this enum must not bloat `MacroCategory` with
    event-specific categories (e.g. `CENTRAL_BANK_COMMUNICATION`, which
    has no numeric value at all and no analog in `MacroCategory`) that
    it was never scoped to hold.
    """

    POLICY_RATE_DECISION = "POLICY_RATE_DECISION"
    INFLATION = "INFLATION"
    EMPLOYMENT = "EMPLOYMENT"
    GROWTH = "GROWTH"
    RETAIL_SALES = "RETAIL_SALES"
    CENTRAL_BANK_COMMUNICATION = "CENTRAL_BANK_COMMUNICATION"
