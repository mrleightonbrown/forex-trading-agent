from enum import Enum


class NewsTopic(Enum):
    """FX-59 Section 32: a CLOSED v1 macro evidence taxonomy, sized
    for FX trading context -- deliberately a small, coarse set of
    categories, not dozens of fine-grained ones.

    A story may legitimately classify under several topics at once, or
    none at all (Section 33) -- this enum describes WHAT a story may
    be about, never a ranking or an exclusive choice. There is no
    `OTHER` member (Section 33): zero topics is itself a valid,
    meaningful result, never papered over with a catch-all."""

    MONETARY_POLICY = "MONETARY_POLICY"
    INFLATION_PRICES = "INFLATION_PRICES"
    LABOUR_EMPLOYMENT = "LABOUR_EMPLOYMENT"
    GROWTH_ACTIVITY = "GROWTH_ACTIVITY"
    INTERNATIONAL_TRADE = "INTERNATIONAL_TRADE"
    FISCAL_POLICY = "FISCAL_POLICY"
    FINANCIAL_STABILITY = "FINANCIAL_STABILITY"
    BANKING_REGULATION = "BANKING_REGULATION"
    EXCHANGE_RATES = "EXCHANGE_RATES"
