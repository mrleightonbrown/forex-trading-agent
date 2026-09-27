"""FX-54: which side of an FX pair one economic-event currency concerns.

Deliberately a small, factual, non-directional classification -- see
this module's own `pair_role_by_indicator_key` docstring for why this
must never be read as a bullish/bearish/directional signal.
"""

from enum import Enum

from forex_agent.domain.economic_indicator_registry import indicators_by_currency
from forex_agent.domain.instrument import Instrument


class PairCurrencyRole(Enum):
    """Whether an economic event's own currency is this pair's BASE or
    QUOTE side (FX-54 Section 6) -- structural evidence only. This
    says nothing about direction: a BASE-currency event is not "good
    for the base" and a QUOTE-currency event is not "bad for the
    quote." Any such interpretation is a Decision/Risk-Engine policy
    concern, entirely out of this evidence layer's scope."""

    BASE = "BASE"
    QUOTE = "QUOTE"


def pair_role_by_indicator_key(instrument: Instrument) -> dict[str, PairCurrencyRole]:
    """Every canonical indicator key currently tracked for either side
    of `instrument`, mapped to which side it concerns -- FX-54's own
    pair-relevance mechanism (Section 5): "an event is pair-relevant
    when its canonical indicator currency is one of the two currencies
    in the pair," resolved exclusively through `EconomicIndicatorDefinition.
    currency` via `indicators_by_currency`, never by inferring currency
    from an indicator's name, source, or occurrence key.

    `Instrument.__post_init__` already guarantees `base_currency !=
    quote_currency`, so no indicator key can ever be assigned both
    roles. A currency with zero tracked indicators (e.g. EUR, as of
    FX-52A/FX-54) simply contributes no entries -- callers must read
    that as structural incompleteness (see `domain.event_coverage_
    evidence`), never as "nothing to track."
    """
    roles: dict[str, PairCurrencyRole] = {}
    for indicator in indicators_by_currency(instrument.base_currency):
        roles[indicator.key] = PairCurrencyRole.BASE
    for indicator in indicators_by_currency(instrument.quote_currency):
        roles[indicator.key] = PairCurrencyRole.QUOTE
    return roles
