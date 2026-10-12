import pytest

from forex_agent.domain.news_semantic_source_profile import (
    UnsupportedNewsSemanticSourceError,
    get_source_semantic_profile,
)

# FX-59 Section 19/68: pin all six required source-profile mappings.
_EXPECTED_PROFILES = {
    "FED": ("FEDERAL_RESERVE", "UNITED_STATES", "USD"),
    "ECB": ("EUROPEAN_CENTRAL_BANK", "EURO_AREA", "EUR"),
    "BOE": ("BANK_OF_ENGLAND", "UNITED_KINGDOM", "GBP"),
    "GOVUK_HMT": ("HM_TREASURY", "UNITED_KINGDOM", "GBP"),
    "STATCAN": ("STATISTICS_CANADA", "CANADA", "CAD"),
    "BOC": ("BANK_OF_CANADA", "CANADA", "CAD"),
}


@pytest.mark.parametrize("source_key", sorted(_EXPECTED_PROFILES))
def test_every_adopted_source_has_the_expected_profile(source_key: str) -> None:
    institution, jurisdiction, currency = _EXPECTED_PROFILES[source_key]
    profile = get_source_semantic_profile(source_key)
    assert profile.institution_entity_key == institution
    assert profile.jurisdiction_entity_key == jurisdiction
    assert profile.primary_currency == currency


def test_unknown_source_fails_closed() -> None:
    with pytest.raises(UnsupportedNewsSemanticSourceError, match="UNKNOWN_SOURCE"):
        get_source_semantic_profile("UNKNOWN_SOURCE")
