from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NewsSourceDefinition:
    """Stable technical metadata for one admitted news source (FX-56
    Section 30) -- mirrors `domain.economic_indicator_definition.
    EconomicIndicatorDefinition`'s own role for economic indicators.

    Deliberately carries NO rights/licensing/admission prose, and NO
    reputation/credibility/trust/ranking of any kind (FX-56 Section
    29/30/39): ADR 0005 remains the sole rights/admission authority,
    and source reputation is explicitly FX-EPIC-09's own future
    territory, never this codebase's. This type exists only so
    `domain.news_source_registry`'s own six entries have one
    consistent, testable shape to confirm against -- it is never
    enforced by `NewsRepository` (a `source_key` passed to that port
    is an opaque string; the repository does not look it up here).

    Fields:
        source_key: the stable string identity used as `domain.
            news_source_identity.NewsSourceIdentity.source_key`.
        display_name: human-readable name (e.g. "Federal Reserve
            Board / FOMC").
        source_family: a free-form descriptive grouping (e.g.
            "CENTRAL_BANK", "GOVERNMENT_DEPARTMENT",
            "STATISTICAL_AGENCY") -- not enforced against a fixed
            vocabulary, same convention as `EconomicIndicatorDefinition.
            unit`.
        admitted_for_prospective_text: whether ADR 0005/FX-55H admits
            this source for prospective, text-bearing ingestion. Every
            entry in `domain.news_source_registry` is `True` by
            construction -- a source ADR 0005 did not admit (BEA,
            GDELT, any commercial provider, ...) simply has no entry
            at all, exactly as `domain.economic_indicator_registry`'s
            own "EUR has no entry" convention already established.
    """

    source_key: str
    display_name: str
    source_family: str
    admitted_for_prospective_text: bool

    def __post_init__(self) -> None:
        if not isinstance(self.source_key, str) or not self.source_key.strip():
            raise ValueError(f"source_key must be a non-empty string, got {self.source_key!r}")
        if not isinstance(self.display_name, str) or not self.display_name.strip():
            raise ValueError(f"display_name must be a non-empty string, got {self.display_name!r}")
        if not isinstance(self.source_family, str) or not self.source_family.strip():
            raise ValueError(
                f"source_family must be a non-empty string, got {self.source_family!r}"
            )
        if not isinstance(self.admitted_for_prospective_text, bool):
            raise TypeError(
                "admitted_for_prospective_text must be a bool, got "
                f"{type(self.admitted_for_prospective_text).__name__}"
            )
