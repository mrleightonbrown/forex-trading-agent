from enum import Enum


class SourceEvidenceKind(Enum):
    """FX-62 Section 5: the category of evidence supporting a CONFIRMED
    identity or attribution vintage -- every confirmed assertion must
    name WHY FTA believes it, never a bare assertion with no
    provenance. Mirrors `domain.news_entity_evidence_kind.
    NewsEntityEvidenceKind`'s own role for FX-59's own entity
    annotations."""

    #: The feed's own already-reviewed adapter configuration (e.g.
    #: `domain.news_source_registry`/`domain.news_semantic_source_
    #: profile`'s own per-`source_key` institution mapping) -- never a
    #: live network call, never inferred from free text.
    ADAPTER_CONFIGURATION = "ADAPTER_CONFIGURATION"

    #: Explicit publisher/author metadata embedded in the source-
    #: native record itself (e.g. a feed's own `<author>`/byline
    #: field), distinct from FTA's own adapter configuration.
    SOURCE_NATIVE_METADATA = "SOURCE_NATIVE_METADATA"

    #: An authoritative identity reference available to FTA (e.g. a
    #: stable canonical website/identifier for the actor), independent
    #: of any one specific NewsItem.
    AUTHORITATIVE_REFERENCE = "AUTHORITATIVE_REFERENCE"

    #: A separately reviewed manual attribution -- the recorded
    #: `description` must name the reviewing actor and reason (FX-62
    #: Section 5's own explicit requirement).
    MANUAL_REVIEW = "MANUAL_REVIEW"
