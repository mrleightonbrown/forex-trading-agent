from dataclasses import dataclass

from forex_agent.domain.source_attribution_role import SourceAttributionRole
from forex_agent.domain.source_attribution_status import SourceAttributionStatus
from forex_agent.domain.source_provenance_evidence import SourceProvenanceEvidence
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class SourceAttributionVintage:
    """FX-62 Section 4.3: an append-only attribution linking one
    `NewsItem` to one identified actor's own `SourceAttributionRole`,
    as FTA understood it at `availability`. The natural identity is
    `(news_item_key, role, revision_sequence)` -- EACH role carries
    its OWN independent revision history (a PUBLISHER correction never
    touches ORIGINATING_CLAIMANT's own history, and vice versa).

    `evidence_basis_revision_sequence` pins the EXACT `NewsItemVintage`
    this attribution was actually evaluated against (mirrors FX-59's
    own `basis_news_item_revision_sequence` precedent exactly) -- the
    attribution content is never copied from that vintage, only
    referenced, so it can always be audited against the real evidence
    that produced it."""

    news_item_key: str
    role: SourceAttributionRole
    revision_sequence: int
    availability: UtcTimestamp
    algorithm_version: str
    status: SourceAttributionStatus
    attributed_source_key: str | None
    """The `IntelligenceSource.source_key` this role is attributed to
    -- REQUIRED (non-`None`) iff `status is CONFIRMED`; REQUIRED to be
    `None` iff `status is UNRESOLVED` (Section 4.4's own invariant,
    enforced here so an inconsistent combination can never even be
    constructed)."""

    evidence_basis_revision_sequence: int
    evidence: SourceProvenanceEvidence
    corrects_revision_sequence: int | None = None
    """FX-62 Section 9: set when this vintage explicitly corrects an
    earlier, mistaken confirmed/unresolved vintage for the SAME (news_
    item_key, role) pair -- purely informational/audit, mirrors
    `SourceIdentityVintage.correction_reason`'s own role; never changes
    how historical resolution selects the latest-as-of vintage."""

    def __post_init__(self) -> None:
        if not isinstance(self.news_item_key, str) or not self.news_item_key.strip():
            raise ValueError(
                f"news_item_key must be a non-empty string, got {self.news_item_key!r}"
            )
        if not isinstance(self.role, SourceAttributionRole):
            raise TypeError(f"role must be a SourceAttributionRole, got {type(self.role).__name__}")
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
        if not isinstance(self.status, SourceAttributionStatus):
            raise TypeError(
                f"status must be a SourceAttributionStatus, got {type(self.status).__name__}"
            )

        if self.status is SourceAttributionStatus.CONFIRMED:
            if (
                not isinstance(self.attributed_source_key, str)
                or not self.attributed_source_key.strip()
            ):
                raise ValueError(
                    "attributed_source_key must be a non-empty string when status is CONFIRMED, "
                    f"got {self.attributed_source_key!r}"
                )
        elif self.attributed_source_key is not None:
            raise ValueError(
                "attributed_source_key must be None when status is UNRESOLVED, got "
                f"{self.attributed_source_key!r}"
            )

        if not isinstance(self.evidence_basis_revision_sequence, int) or isinstance(
            self.evidence_basis_revision_sequence, bool
        ):
            raise TypeError(
                "evidence_basis_revision_sequence must be an int, got "
                f"{type(self.evidence_basis_revision_sequence).__name__}"
            )
        if self.evidence_basis_revision_sequence < 0:
            raise ValueError("evidence_basis_revision_sequence must not be negative")
        if not isinstance(self.evidence, SourceProvenanceEvidence):
            raise TypeError(
                f"evidence must be a SourceProvenanceEvidence, got {type(self.evidence).__name__}"
            )
        if self.corrects_revision_sequence is not None:
            if not isinstance(self.corrects_revision_sequence, int) or isinstance(
                self.corrects_revision_sequence, bool
            ):
                raise TypeError(
                    "corrects_revision_sequence must be None or an int, got "
                    f"{type(self.corrects_revision_sequence).__name__}"
                )
            if self.corrects_revision_sequence < 0:
                raise ValueError("corrects_revision_sequence must not be negative")
            if self.corrects_revision_sequence >= self.revision_sequence:
                raise ValueError(
                    "corrects_revision_sequence must be strictly less than this vintage's own "
                    f"revision_sequence, got corrects={self.corrects_revision_sequence!r}, "
                    f"revision_sequence={self.revision_sequence!r}"
                )
