from dataclasses import dataclass

from forex_agent.domain.source_evidence_kind import SourceEvidenceKind


@dataclass(frozen=True, slots=True)
class SourceProvenanceEvidence:
    """FX-62 Section 4.2/4.3/5: the exact, human-readable reason FTA
    believes ONE identity or attribution vintage -- required on EVERY
    `SourceIdentityVintage`/`SourceAttributionVintage`, confirmed or
    not, so provenance is always auditable (Section 4's own "the exact
    evidence supporting an attribution" requirement). Never a bare
    assertion with no provenance; never inferred from unapproved NLP/
    LLM classification (Section 5's own explicit prohibition)."""

    evidence_kind: SourceEvidenceKind
    description: str

    def __post_init__(self) -> None:
        if not isinstance(self.evidence_kind, SourceEvidenceKind):
            raise TypeError(
                "evidence_kind must be a SourceEvidenceKind, got "
                f"{type(self.evidence_kind).__name__}"
            )
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError(f"description must be a non-empty string, got {self.description!r}")
