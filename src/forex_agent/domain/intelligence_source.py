from dataclasses import dataclass

from forex_agent.domain.intelligence_source_kind import IntelligenceSourceKind
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class IntelligenceSource:
    """FX-62 Section 4.1: a durable source identity -- deliberately
    minimal and immutable, mirroring `domain.news_item.NewsItem`'s own
    "three fields only, written exactly once" shape. Every EVOLVING
    fact about this identity (display name, aliases, authoritative
    reference) lives on a SEPARATE, append-only `SourceIdentityVintage`
    series keyed by `source_key` -- never here.

    `source_key` is the identity's own durable, immutable string key
    -- NEVER reassigned to a different actor, and NEVER the same
    namespace as `domain.news_source_identity.NewsSourceIdentity.
    source_key` by coincidence of meaning: a `TECHNICAL_FEED`-kind
    `IntelligenceSource` MAY reuse the exact same string FX-57's own
    `NewsSourceIdentity.source_key` already uses for that feed (e.g.
    `"BOE"`), since that string already uniquely names the feed --
    but an `ORGANIZATION`-kind `IntelligenceSource` for the Bank of
    England itself is a GENUINELY DIFFERENT identity (and should use a
    genuinely different key, e.g. `"BANK_OF_ENGLAND"`, reusing FX-59's
    own already-reviewed `institution_entity_key` convention from
    `domain.news_semantic_source_profile`) -- identity is not
    reputation, and a feed is not automatically the same actor as its
    publisher (Section 4.1's own explicit warning)."""

    source_key: str
    source_kind: IntelligenceSourceKind
    registered_at: UtcTimestamp
    """FTA's own registration time for this durable identity -- never
    backdated to when the underlying real-world actor was founded, and
    never the same concept as any `SourceIdentityVintage.availability`
    (Section 6's own explicit "do not backdate identity knowledge"
    requirement)."""

    def __post_init__(self) -> None:
        if not isinstance(self.source_key, str) or not self.source_key.strip():
            raise ValueError(f"source_key must be a non-empty string, got {self.source_key!r}")
        if not isinstance(self.source_kind, IntelligenceSourceKind):
            raise TypeError(
                "source_kind must be an IntelligenceSourceKind, got "
                f"{type(self.source_kind).__name__}"
            )
        if not isinstance(self.registered_at, UtcTimestamp):
            raise TypeError(
                f"registered_at must be a UtcTimestamp, got {type(self.registered_at).__name__}"
            )
