from dataclasses import dataclass

from forex_agent.domain.news_entity_evidence_kind import NewsEntityEvidenceKind
from forex_agent.domain.news_entity_type import NewsEntityType


@dataclass(frozen=True, slots=True)
class NewsEntityAnnotation:
    """One macro entity FTA's `fx59_v1` classifier found for one
    `NewsItem` (FX-59 Section 16/17/21).

    `entity_key` is a stable, internal identifier (e.g.
    `"FEDERAL_RESERVE"`), never display text -- display names/aliases
    live only in the classifier's own registry (FX-59 Section 17),
    never in stored identity. Deliberately NOT constrained to a fixed
    database enumeration (Section 18): new institutions/jurisdictions
    can be added to the classifier's registry in a future story
    without any schema migration or loss of readability for historical
    rows; this type validates only that the key is non-blank and that
    `entity_type` is a recognized `NewsEntityType`.

    `evidence` is a non-empty, canonically sorted, deduplicated tuple
    of `NewsEntityEvidenceKind` -- never blank, and a single entity
    never carries two annotations for the same item; if more than one
    kind of evidence supports the same entity, they are consolidated
    into ONE annotation's own `evidence` tuple (Section 21)."""

    entity_type: NewsEntityType
    entity_key: str
    evidence: tuple[NewsEntityEvidenceKind, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.entity_type, NewsEntityType):
            raise TypeError(
                f"entity_type must be a NewsEntityType, got {type(self.entity_type).__name__}"
            )
        if not isinstance(self.entity_key, str) or not self.entity_key.strip():
            raise ValueError(f"entity_key must be a non-empty string, got {self.entity_key!r}")
        if not isinstance(self.evidence, tuple) or not self.evidence:
            raise ValueError(f"evidence must be a non-empty tuple, got {self.evidence!r}")
        for kind in self.evidence:
            if not isinstance(kind, NewsEntityEvidenceKind):
                raise TypeError(
                    "each evidence entry must be a NewsEntityEvidenceKind, got "
                    f"{type(kind).__name__}"
                )
        if len(set(self.evidence)) != len(self.evidence):
            raise ValueError(f"evidence must not contain duplicates, got {self.evidence!r}")
        canonical_evidence = tuple(sorted(self.evidence, key=lambda k: k.value))
        if self.evidence != canonical_evidence:
            raise ValueError(
                f"evidence must be in canonical sorted order, got {self.evidence!r}, "
                f"expected {canonical_evidence!r}"
            )
