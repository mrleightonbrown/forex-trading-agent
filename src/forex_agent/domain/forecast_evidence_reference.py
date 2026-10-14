from dataclasses import dataclass

from forex_agent.domain._guards import require_revision_sequence
from forex_agent.domain.forecast_evidence_kind import ForecastEvidenceKind
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class ForecastEvidenceReference:
    """FX-64 Section 6: the EXACT supporting evidence for one
    structured-forecast vintage. `description` is always required
    (mirrors FX-62's own `SourceProvenanceEvidence.description`) --
    a human-auditable account of what was actually read. Exactly one
    of the two evidence shapes applies, enforced structurally:

    - `NEWS_ITEM_VINTAGE_BASIS`: `news_item_key` + `basis_revision_
      sequence` REQUIRED (pins an exact `NewsItemVintage`, mirroring
      FX-59/62's own composite basis-pinning FK convention);
      `document_identifier` FORBIDDEN.
    - `EXTERNAL_DOCUMENT_REFERENCE`: `document_identifier` REQUIRED
      (the source's own stable identifier for this document, e.g.
      `"ECB SPF 2025Q1"`); `news_item_key`/`basis_revision_sequence`
      FORBIDDEN.

    `document_locator`/`official_reference_url`/`content_fingerprint`/
    `publisher_declared_publication_at` are all OPTIONAL regardless of
    kind -- additional, never-required archival/integrity metadata.
    `publisher_declared_publication_at` is PURELY descriptive (Section
    6/7) -- never promoted to a vintage's own `availability`, mirroring
    FX-55H's own "FTA knowledge, not source timestamp" invariant.

    **FX-64H (H2) boundary**: everything enforced here is STRUCTURAL
    shape only -- which fields are present, and whether they are non-
    empty strings/well-typed timestamps. Constructing an instance of
    this class NEVER constitutes, implies, or substitutes for
    independent authentication that the referenced document actually
    exists, is genuine, or says what `description` claims. No field
    here (including `content_fingerprint`) is verified against the
    real document by this code; a caller must never populate
    `content_fingerprint` with a value it has not itself computed
    from the real content, and must never treat a well-formed
    `document_identifier` as proof of authenticity. That authentication
    is a human, out-of-band responsibility exercised BEFORE a candidate
    is ever constructed (e.g. by whoever curates a pilot import) --
    this story deliberately adds no automated verification service for
    it."""

    evidence_kind: ForecastEvidenceKind
    description: str
    news_item_key: str | None = None
    basis_revision_sequence: int | None = None
    document_identifier: str | None = None
    document_locator: str | None = None
    official_reference_url: str | None = None
    content_fingerprint: str | None = None
    publisher_declared_publication_at: UtcTimestamp | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.evidence_kind, ForecastEvidenceKind):
            raise TypeError(
                f"evidence_kind must be a ForecastEvidenceKind, got "
                f"{type(self.evidence_kind).__name__}"
            )
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError(f"description must be a non-empty string, got {self.description!r}")
        for optional_text in (
            self.news_item_key,
            self.document_identifier,
            self.document_locator,
            self.official_reference_url,
            self.content_fingerprint,
        ):
            if optional_text is not None and (
                not isinstance(optional_text, str) or not optional_text.strip()
            ):
                raise ValueError(
                    f"optional text fields must be non-empty strings or None, got {optional_text!r}"
                )
        if self.publisher_declared_publication_at is not None and not isinstance(
            self.publisher_declared_publication_at, UtcTimestamp
        ):
            raise TypeError(
                "publisher_declared_publication_at must be a UtcTimestamp or None, got "
                f"{type(self.publisher_declared_publication_at).__name__}"
            )

        if self.evidence_kind is ForecastEvidenceKind.NEWS_ITEM_VINTAGE_BASIS:
            if self.news_item_key is None:
                raise ValueError("news_item_key is required for NEWS_ITEM_VINTAGE_BASIS")
            if self.basis_revision_sequence is None:
                raise ValueError("basis_revision_sequence is required for NEWS_ITEM_VINTAGE_BASIS")
            require_revision_sequence(self.basis_revision_sequence)
            if self.document_identifier is not None:
                raise ValueError("document_identifier must be None for NEWS_ITEM_VINTAGE_BASIS")
        elif self.evidence_kind is ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE:
            if self.document_identifier is None:
                raise ValueError("document_identifier is required for EXTERNAL_DOCUMENT_REFERENCE")
            if self.news_item_key is not None or self.basis_revision_sequence is not None:
                raise ValueError(
                    "news_item_key/basis_revision_sequence must be None for "
                    "EXTERNAL_DOCUMENT_REFERENCE"
                )
