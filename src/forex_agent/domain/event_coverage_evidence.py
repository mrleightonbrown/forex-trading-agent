"""FX-54 Section 19/21: structural coverage limitations for one FX
pair -- the ONE mechanism this story provides for a caller to tell
"no PIT-visible event among the indicators/sources currently tracked
falls inside the requested window" apart from "there is no economic-
event risk." Given this project's deliberately partial FX-52A
coverage (BLS blocked by an HTTP 403, EUR with zero adopted source at
all), an empty evidence list MUST NOT be read as "safe" -- this type
exists so a caller always has the structural context needed to avoid
that misreading, without this evidence layer ever emitting an
`all_clear`/`safe_to_trade`/`no_event_risk` flag itself (FX-54 Section
20 forbids exactly that).

Deliberately does NOT attempt to report live source health/freshness
(e.g. "was BLS reachable in the last poll") -- no durable source-
health/poll-state metadata exists anywhere in this repository for the
economic-calendar subsystem (the closest analog,
`IngestionWatermarkRepository`, belongs to the unrelated OANDA-candle-
backfill bounded context). Per FX-54 Section 21's own explicit
instruction, this is stated honestly rather than invented: this type
reports only which canonical indicators this pair's currencies
currently have in the registry, never whether their underlying source
is currently operational.
"""

from dataclasses import dataclass

from forex_agent.domain.economic_indicator_registry import indicators_by_currency


@dataclass(frozen=True, slots=True)
class EventCoverageEvidence:
    """Fields:
    base_currency/quote_currency: this pair's own two currencies,
        verbatim from the requested `Instrument`.
    tracked_indicator_keys_by_currency: `((currency, indicator_keys),
        ...)` for `base_currency` then `quote_currency`, each
        `indicator_keys` sorted alphabetically -- every canonical
        indicator this registry currently has for that currency,
        REGARDLESS of whether any evidence for it fell inside the
        requested window. An empty `indicator_keys` tuple for a
        currency is the honest structural fact "this subsystem
        currently tracks zero indicators for this currency"
        (true for EUR as of FX-52A/FX-54).
    untracked_pair_currencies: the subset of `{base_currency,
        quote_currency}` with zero tracked indicators at all --
        e.g. `("EUR",)` for any EUR pair today. Empty when both
        currencies have at least one tracked indicator (this does
        NOT mean "fully covered," only "at least one indicator
        exists" -- coverage may still be narrow, e.g. GBP has only
        `GBP_GDP_QOQ`).
    """

    base_currency: str
    quote_currency: str
    tracked_indicator_keys_by_currency: tuple[tuple[str, tuple[str, ...]], ...]
    untracked_pair_currencies: tuple[str, ...]


def build_coverage_evidence(base_currency: str, quote_currency: str) -> EventCoverageEvidence:
    """Pure, registry-only construction -- no I/O, no repository
    access; this is a static fact about the canonical indicator
    registry's own current contents, independent of `as_of` or any
    persisted event data."""
    tracked: list[tuple[str, tuple[str, ...]]] = []
    untracked: list[str] = []
    for currency in (base_currency, quote_currency):
        keys = tuple(sorted(d.key for d in indicators_by_currency(currency)))
        tracked.append((currency, keys))
        if not keys:
            untracked.append(currency)
    return EventCoverageEvidence(
        base_currency=base_currency,
        quote_currency=quote_currency,
        tracked_indicator_keys_by_currency=tuple(tracked),
        untracked_pair_currencies=tuple(untracked),
    )
