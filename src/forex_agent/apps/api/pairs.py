"""FX-54V: the "Market Context" dashboard's own supported-pair
registry -- deliberately NOT a domain concept (`domain.instrument.
Instrument` itself supports any base/quote combination; nothing in
`domain`/`application` needs to know which three pairs THIS dashboard
happens to expose). No canonical `SUPPORTED_PAIRS`-style constant
exists anywhere else in this codebase to reuse -- every research
script that needs a pair list constructs its own inline `Instrument`
tuple; this is FX-54V's own, presentation-facing equivalent.
"""

from forex_agent.domain.instrument import Instrument

#: FX-54V Section 2's own three pairs. Keys are the URL/query-param form
#: (`BASE_QUOTE`, matching `Instrument.symbol`), values the actual
#: `Instrument`.
SUPPORTED_PAIRS: dict[str, Instrument] = {
    "EUR_USD": Instrument(base_currency="EUR", quote_currency="USD"),
    "GBP_USD": Instrument(base_currency="GBP", quote_currency="USD"),
    "USD_CAD": Instrument(base_currency="USD", quote_currency="CAD"),
}


def resolve_pair(pair_code: str) -> Instrument | None:
    """The `Instrument` for `pair_code` (e.g. `"GBP_USD"`), or `None`
    if `pair_code` is not one of this dashboard's currently-supported
    pairs -- callers must render an explicit "unsupported pair" state,
    never guess or silently substitute a default pair."""
    return SUPPORTED_PAIRS.get(pair_code)
