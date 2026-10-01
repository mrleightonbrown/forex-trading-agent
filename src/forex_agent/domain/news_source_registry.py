"""Canonical registry of the six news sources ADR 0005/FX-55H admit
for prospective, text-bearing ingestion (FX-56 Section 30).

Deliberately small -- six institutions, no others -- mirroring
`domain.economic_indicator_registry`'s own admission discipline: a
source is only added here once ADR 0005 itself has classified it
ADOPT_PROSPECTIVE for text-bearing evidence. BEA (DEFER -- unresolved
reuse rights), the ECB's own bulk speeches CSV (DEFER_HISTORICAL --
prospective REJECT regardless), GOV.UK's own Search API (DEFER -- own
terms unverified), GDELT's bulk GKG channel (ADOPT_AUXILIARY_METADATA
-- metadata-only, no headline/text under any rights posture, and
explicitly excluded from this text-bearing scope), every general
financial news provider (class B), every other commercial news API/
aggregator (class C), and every dedicated FX-commentary publisher
(class D) have NO entry here -- not because they were overlooked, but
because ADR 0005 did not admit them, exactly as `domain.economic_
indicator_registry`'s own "EUR has no entry" convention already
established for an indicator with no cleared source.

This registry is documentation/scope confirmation only -- see
`NewsSourceDefinition`'s own docstring for why `NewsRepository` never
looks a `source_key` up against it.
"""

from forex_agent.domain.news_source_definition import NewsSourceDefinition

FEDERAL_RESERVE = NewsSourceDefinition(
    source_key="FED",
    display_name="Federal Reserve Board / FOMC",
    source_family="CENTRAL_BANK",
    admitted_for_prospective_text=True,
)

ECB = NewsSourceDefinition(
    source_key="ECB",
    display_name="European Central Bank (combined press/speech/interview feed)",
    source_family="CENTRAL_BANK",
    admitted_for_prospective_text=True,
)

BANK_OF_ENGLAND = NewsSourceDefinition(
    source_key="BOE",
    display_name="Bank of England",
    source_family="CENTRAL_BANK",
    admitted_for_prospective_text=True,
)

GOVUK_HM_TREASURY = NewsSourceDefinition(
    source_key="GOVUK_HMT",
    display_name="GOV.UK Content API (HM Treasury)",
    source_family="GOVERNMENT_DEPARTMENT",
    admitted_for_prospective_text=True,
)

STATISTICS_CANADA = NewsSourceDefinition(
    source_key="STATCAN",
    display_name="Statistics Canada (The Daily)",
    source_family="STATISTICAL_AGENCY",
    admitted_for_prospective_text=True,
)

BANK_OF_CANADA = NewsSourceDefinition(
    source_key="BOC",
    display_name="Bank of Canada (press-releases feed only)",
    source_family="CENTRAL_BANK",
    admitted_for_prospective_text=True,
)

_REGISTRY: dict[str, NewsSourceDefinition] = {
    definition.source_key: definition
    for definition in (
        FEDERAL_RESERVE,
        ECB,
        BANK_OF_ENGLAND,
        GOVUK_HM_TREASURY,
        STATISTICS_CANADA,
        BANK_OF_CANADA,
    )
}


def source_by_key(source_key: str) -> NewsSourceDefinition | None:
    """The admitted `NewsSourceDefinition` at `source_key`, or `None`
    if ADR 0005 has not admitted a source under that key -- mirrors
    `domain.economic_indicator_registry.indicator_by_key`."""
    return _REGISTRY.get(source_key)


def admitted_prospective_text_source_keys() -> frozenset[str]:
    """Every `source_key` currently admitted for prospective,
    text-bearing ingestion -- exactly the six ADR 0005/FX-55H names."""
    return frozenset(_REGISTRY.keys())
