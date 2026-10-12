"""FX-59 Section 19/20: a curated, deterministic source-profile
registry for the six ADR-0005-adopted news sources -- publisher
institution, jurisdiction, and primary currency are explicit SOURCE-
PROFILE FACTS, never inferred from headline text (Section 19's own
"Do not infer these from headlines").

`get_source_semantic_profile` FAILS CLOSED for any `source_key` not
in this registry (Section 20) -- a newly-added seventh source must be
explicitly reviewed and given its own profile here before `Classify
NewsOnce` will classify any of its items; it must never silently fall
through to "no entities, no currency relevance" for a source nobody
has reviewed."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NewsSemanticSourceProfile:
    """One source's own structural semantic facts (FX-59 Section 19)
    -- never derived from any one item's own text."""

    source_key: str
    institution_entity_key: str
    jurisdiction_entity_key: str
    primary_currency: str


class UnsupportedNewsSemanticSourceError(Exception):
    """Raised when `ClassifyNewsOnce`/`classify_news_semantics`
    encounters an evidence-eligible candidate whose `source_key` has
    no registered semantic source profile (FX-59 Section 20) -- fails
    BEFORE persistence, never silently emitting an entity-less,
    currency-relevance-less annotation for an unreviewed source."""

    def __init__(self, source_key: str) -> None:
        self.source_key = source_key
        super().__init__(
            f"no NewsSemanticSourceProfile is registered for source_key={source_key!r} -- "
            "refusing to classify an item from a source that has not been explicitly reviewed"
        )


_SOURCE_SEMANTIC_PROFILES: dict[str, NewsSemanticSourceProfile] = {
    profile.source_key: profile
    for profile in (
        NewsSemanticSourceProfile(
            source_key="FED",
            institution_entity_key="FEDERAL_RESERVE",
            jurisdiction_entity_key="UNITED_STATES",
            primary_currency="USD",
        ),
        NewsSemanticSourceProfile(
            source_key="ECB",
            institution_entity_key="EUROPEAN_CENTRAL_BANK",
            jurisdiction_entity_key="EURO_AREA",
            primary_currency="EUR",
        ),
        NewsSemanticSourceProfile(
            source_key="BOE",
            institution_entity_key="BANK_OF_ENGLAND",
            jurisdiction_entity_key="UNITED_KINGDOM",
            primary_currency="GBP",
        ),
        NewsSemanticSourceProfile(
            source_key="GOVUK_HMT",
            institution_entity_key="HM_TREASURY",
            jurisdiction_entity_key="UNITED_KINGDOM",
            primary_currency="GBP",
        ),
        NewsSemanticSourceProfile(
            source_key="STATCAN",
            institution_entity_key="STATISTICS_CANADA",
            jurisdiction_entity_key="CANADA",
            primary_currency="CAD",
        ),
        NewsSemanticSourceProfile(
            source_key="BOC",
            institution_entity_key="BANK_OF_CANADA",
            jurisdiction_entity_key="CANADA",
            primary_currency="CAD",
        ),
    )
}


def get_source_semantic_profile(source_key: str) -> NewsSemanticSourceProfile:
    """Returns the registered profile for `source_key`, or raises
    `UnsupportedNewsSemanticSourceError` (Section 20) -- never
    returns `None`, so a caller cannot forget to check."""
    profile = _SOURCE_SEMANTIC_PROFILES.get(source_key)
    if profile is None:
        raise UnsupportedNewsSemanticSourceError(source_key)
    return profile
