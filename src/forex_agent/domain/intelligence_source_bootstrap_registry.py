"""FX-62 Section 6: the six-source bootstrap mapping candidate -- a
TECHNICAL_FEED-to-ORGANIZATION pairing for each of ADR 0005/FX-55H's
own six admitted news sources. Deliberately REUSES, never duplicates,
the two already-reviewed registries this mapping is built from:

- `domain.news_source_registry` (FX-56): each feed's own `source_key`
  and `display_name` -- the SAME string `BootstrapSourceRegistry` will
  use as the TECHNICAL_FEED `IntelligenceSource.source_key`.
- `domain.news_semantic_source_profile` (FX-59): each feed's own
  `institution_entity_key` -- reused VERBATIM as the ORGANIZATION
  `IntelligenceSource.source_key`, so FX-62's own registry and FX-59's
  own classifier output always speak about the SAME institution under
  the SAME key, with no silent drift between the two.

**FX-62 Section 6's own explicit verification requirement**: "verify
that FED does not contain heterogeneous Federal Reserve institutions
requiring a more precise publisher identity." Confirmed directly
against `infrastructure.news_sources.fed_rss_source`'s own docstring
and channel definitions (FX-57A): all three Fed channels (`press_
monetary`/`speeches`/`testimony`) are monetary-policy press releases,
speeches, AND congressional testimony -- all attributable to the SAME
institution (the Federal Reserve Board / FOMC), never a distinct sub-
institution. `FED` maps 1:1 to `FEDERAL_RESERVE` safely.

This module is a MAPPING CANDIDATE only (Section 6's own explicit
framing) -- `BootstrapSourceRegistry` is the application-layer use
case that actually performs the idempotent registration; this module
contributes no I/O, no persistence, and no network access of its
own."""

from dataclasses import dataclass

from forex_agent.domain import news_source_registry
from forex_agent.domain.news_semantic_source_profile import get_source_semantic_profile


@dataclass(frozen=True, slots=True)
class IntelligenceSourceBootstrapMapping:
    """One feed's own bootstrap candidate: its TECHNICAL_FEED identity
    (reusing FX-56's own `source_key`/`display_name`) paired with its
    publishing ORGANIZATION identity (reusing FX-59's own
    `institution_entity_key` as that organization's own durable
    `source_key`)."""

    feed_source_key: str
    feed_display_name: str
    organization_source_key: str
    organization_display_name: str


def _mapping_for(
    feed_source_key: str, organization_display_name: str
) -> IntelligenceSourceBootstrapMapping:
    feed_definition = news_source_registry.source_by_key(feed_source_key)
    if feed_definition is None:
        raise ValueError(
            f"feed_source_key={feed_source_key!r} is not admitted in domain.news_source_registry"
        )
    profile = get_source_semantic_profile(feed_source_key)
    return IntelligenceSourceBootstrapMapping(
        feed_source_key=feed_definition.source_key,
        feed_display_name=feed_definition.display_name,
        organization_source_key=profile.institution_entity_key,
        organization_display_name=organization_display_name,
    )


#: FX-62 Section 6's own six-source bootstrap table. Each entry's own
#: `organization_display_name` is a plain, human-readable rendering of
#: the SAME institution `news_semantic_source_profile.py` already
#: names via `institution_entity_key` -- never a new institutional
#: claim, purely a presentation-friendly label for that already-
#: reviewed identity.
INTELLIGENCE_SOURCE_BOOTSTRAP_MAPPINGS: tuple[IntelligenceSourceBootstrapMapping, ...] = (
    _mapping_for("FED", "Federal Reserve Board / FOMC"),
    _mapping_for("ECB", "European Central Bank"),
    _mapping_for("BOE", "Bank of England"),
    _mapping_for("GOVUK_HMT", "HM Treasury"),
    _mapping_for("STATCAN", "Statistics Canada"),
    _mapping_for("BOC", "Bank of Canada"),
)
