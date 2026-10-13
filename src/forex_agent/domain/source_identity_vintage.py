from dataclasses import dataclass

from forex_agent.domain.source_provenance_evidence import SourceProvenanceEvidence
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class SourceIdentityVintage:
    """FX-62 Section 4.2: FTA's own knowledge about an `IntelligenceSource`
    identity at a particular instant -- append-only, mirroring `domain.
    news_item_vintage.NewsItemVintage`'s own role for raw news content
    and `domain.news_semantic_annotation_vintage.NewsSemanticAnnotation
    Vintage`'s own role for derived classification. A new display name,
    alias, or website is always a NEW vintage, never an overwrite of a
    previous one (Section 4.2's own explicit "do not overwrite or
    delete" requirement) -- `RecordSourceIdentityVintage` is the sole
    application-layer writer of this type."""

    source_key: str
    revision_sequence: int
    availability: UtcTimestamp
    """FTA's own instant of acquiring/recording THIS identity
    assertion -- never the real-world actor's own founding date, never
    a source-native timestamp (Section 8's own PIT discipline, mirrored
    exactly from FX-56's own `NewsItemVintage.availability`)."""

    algorithm_version: str
    display_name: str
    aliases: tuple[str, ...]
    authoritative_identifier: str | None
    canonical_website: str | None
    evidence: SourceProvenanceEvidence
    correction_reason: str | None = None
    """FX-62 Section 4.2/9: set ONLY when this vintage corrects a
    previous MISTAKE in FTA's own prior knowledge (e.g. a wrongly
    recorded display name) -- as opposed to a genuine real-world
    change (e.g. the organization renamed itself), which needs no
    `correction_reason` at all. Purely informational/audit; never
    changes how historical resolution selects the latest-as-of
    vintage."""

    def __post_init__(self) -> None:
        if not isinstance(self.source_key, str) or not self.source_key.strip():
            raise ValueError(f"source_key must be a non-empty string, got {self.source_key!r}")
        if not isinstance(self.revision_sequence, int) or isinstance(self.revision_sequence, bool):
            raise TypeError(
                f"revision_sequence must be an int, got {type(self.revision_sequence).__name__}"
            )
        if self.revision_sequence < 0:
            raise ValueError("revision_sequence must not be negative")
        if not isinstance(self.availability, UtcTimestamp):
            raise TypeError(
                f"availability must be a UtcTimestamp, got {type(self.availability).__name__}"
            )
        if not isinstance(self.algorithm_version, str) or not self.algorithm_version.strip():
            raise ValueError(
                f"algorithm_version must be a non-empty string, got {self.algorithm_version!r}"
            )
        if not isinstance(self.display_name, str) or not self.display_name.strip():
            raise ValueError(f"display_name must be a non-empty string, got {self.display_name!r}")

        if not isinstance(self.aliases, tuple):
            raise TypeError(f"aliases must be a tuple, got {type(self.aliases).__name__}")
        for alias in self.aliases:
            if not isinstance(alias, str) or not alias.strip():
                raise ValueError(f"each alias must be a non-empty string, got {alias!r}")
        if len(set(self.aliases)) != len(self.aliases):
            raise ValueError(f"aliases must not contain a duplicate, got {self.aliases!r}")
        if tuple(sorted(self.aliases)) != self.aliases:
            raise ValueError(f"aliases must be in canonical sorted order, got {self.aliases!r}")

        for optional_text_field in (
            self.authoritative_identifier,
            self.canonical_website,
            self.correction_reason,
        ):
            if optional_text_field is not None and (
                not isinstance(optional_text_field, str) or not optional_text_field.strip()
            ):
                raise ValueError(
                    "authoritative_identifier/canonical_website/correction_reason must each be "
                    f"None or a non-empty string, got {optional_text_field!r}"
                )

        if not isinstance(self.evidence, SourceProvenanceEvidence):
            raise TypeError(
                f"evidence must be a SourceProvenanceEvidence, got {type(self.evidence).__name__}"
            )
