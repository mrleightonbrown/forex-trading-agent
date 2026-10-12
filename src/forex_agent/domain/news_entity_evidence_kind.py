from enum import Enum


class NewsEntityEvidenceKind(Enum):
    """FX-59 Section 21: WHY an entity was emitted for one item --
    preserved so an annotation can be audited, never just "which
    entities" with the reasoning discarded.

    `SOURCE_PROFILE`: the item's own publisher/jurisdiction, from the
    curated `NewsSemanticSourceProfile` registry (never inferred from
    text).
    `TEXT_ALIAS`: an explicit textual mention of the entity, matched
    via a curated, phrase-boundary-safe alias list.

    An entity may carry BOTH kinds at once (e.g. a Federal Reserve
    press release that also says "Federal Reserve" in its own body) --
    consolidated into one annotation, never two."""

    SOURCE_PROFILE = "SOURCE_PROFILE"
    TEXT_ALIAS = "TEXT_ALIAS"
