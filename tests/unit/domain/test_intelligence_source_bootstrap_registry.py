"""FX-62 Section 6/12.D: tests for the six-source bootstrap mapping
candidate table -- validates it reuses `domain.news_source_registry`/
`domain.news_semantic_source_profile` verbatim (never a third,
independently-typed copy of the same six strings), and that the FED
heterogeneity question Section 6 explicitly demands be checked is
genuinely resolved (one feed, one organization)."""

from forex_agent.domain import news_source_registry
from forex_agent.domain.intelligence_source_bootstrap_registry import (
    INTELLIGENCE_SOURCE_BOOTSTRAP_MAPPINGS,
)
from forex_agent.domain.news_semantic_source_profile import get_source_semantic_profile


def test_exactly_six_mappings() -> None:
    assert len(INTELLIGENCE_SOURCE_BOOTSTRAP_MAPPINGS) == 6


def test_every_mapping_feed_key_is_admitted_in_news_source_registry() -> None:
    for mapping in INTELLIGENCE_SOURCE_BOOTSTRAP_MAPPINGS:
        assert news_source_registry.source_by_key(mapping.feed_source_key) is not None


def test_every_mapping_organization_key_reuses_the_fx59_institution_entity_key_verbatim() -> None:
    """Never a third, independently-typed copy of the same six
    institution identities -- FX-62's own organization `source_key`
    must be EXACTLY FX-59's own already-reviewed `institution_entity_
    key`, so the registry and the classifier never silently drift."""
    for mapping in INTELLIGENCE_SOURCE_BOOTSTRAP_MAPPINGS:
        profile = get_source_semantic_profile(mapping.feed_source_key)
        assert mapping.organization_source_key == profile.institution_entity_key


def test_feed_keys_are_exactly_the_six_adr_0005_admitted_sources() -> None:
    feed_keys = {m.feed_source_key for m in INTELLIGENCE_SOURCE_BOOTSTRAP_MAPPINGS}
    assert feed_keys == news_source_registry.admitted_prospective_text_source_keys()


def test_every_feed_maps_to_exactly_one_distinct_organization() -> None:
    """FX-62 Section 6's own explicit requirement to verify FED does
    not contain heterogeneous institutions requiring a more precise
    publisher identity -- this is the structural confirmation that
    every feed maps 1:1 to ONE organization, never split or merged."""
    feed_keys = [m.feed_source_key for m in INTELLIGENCE_SOURCE_BOOTSTRAP_MAPPINGS]
    organization_keys = [m.organization_source_key for m in INTELLIGENCE_SOURCE_BOOTSTRAP_MAPPINGS]
    assert len(feed_keys) == len(set(feed_keys))
    assert len(organization_keys) == len(set(organization_keys))


def test_fed_maps_to_the_single_federal_reserve_organization() -> None:
    """Direct confirmation of the Section 6 verification requirement:
    all three Fed channels (press_monetary/speeches/testimony) are the
    SAME institution (the Federal Reserve Board / FOMC) -- `FED` maps
    to exactly one organization, `FEDERAL_RESERVE`, never a split
    identity per channel."""
    fed_mappings = [m for m in INTELLIGENCE_SOURCE_BOOTSTRAP_MAPPINGS if m.feed_source_key == "FED"]
    assert len(fed_mappings) == 1
    assert fed_mappings[0].organization_source_key == "FEDERAL_RESERVE"


def test_feed_and_organization_keys_never_collide() -> None:
    """A feed's own source_key and its organization's own source_key
    must always be genuinely different strings -- confirms Section
    4.1's own "a feed is not automatically the same actor as its
    publisher" warning holds structurally for all six real mappings."""
    for mapping in INTELLIGENCE_SOURCE_BOOTSTRAP_MAPPINGS:
        assert mapping.feed_source_key != mapping.organization_source_key


def test_display_names_are_non_empty() -> None:
    for mapping in INTELLIGENCE_SOURCE_BOOTSTRAP_MAPPINGS:
        assert mapping.feed_display_name.strip()
        assert mapping.organization_display_name.strip()
