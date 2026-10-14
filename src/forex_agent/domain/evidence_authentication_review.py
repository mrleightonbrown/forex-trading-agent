from dataclasses import dataclass

from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class EvidenceAuthenticationReview:
    """FX-65 Section 8/15: a narrowly-scoped, explicit, human,
    out-of-band attestation that someone independently reviewed a
    piece of evidence against its own primary source -- mirroring
    FX-64H's own H2 lesson ("authenticating a source is a human,
    out-of-band responsibility, never a system field") taken one step
    further: here, that human attestation becomes a first-class,
    required INPUT to evaluation admissibility, rather than living
    only in code comments.

    This is NOT, and must never be read as, proof that the underlying
    evidence is genuine -- it is a record of WHO reviewed it, HOW, and
    WHEN, never manufactured or inferred from the mere existence of a
    structurally valid `ForecastEvidenceReference` (FX-64H's own
    boundary, restated here as a structural guarantee: nothing
    constructs this type automatically). A caller must explicitly
    build one only when a human genuinely performed the review it
    describes."""

    reviewed_by: str
    review_method: str
    reviewed_at: UtcTimestamp
    corroboration_reference: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.reviewed_by, str) or not self.reviewed_by.strip():
            raise ValueError(f"reviewed_by must be a non-empty string, got {self.reviewed_by!r}")
        if not isinstance(self.review_method, str) or not self.review_method.strip():
            raise ValueError(
                f"review_method must be a non-empty string, got {self.review_method!r}"
            )
        if not isinstance(self.reviewed_at, UtcTimestamp):
            raise TypeError(
                f"reviewed_at must be a UtcTimestamp, got {type(self.reviewed_at).__name__}"
            )
        if self.corroboration_reference is not None and (
            not isinstance(self.corroboration_reference, str)
            or not self.corroboration_reference.strip()
        ):
            raise ValueError(
                "corroboration_reference must be a non-empty string or None, got "
                f"{self.corroboration_reference!r}"
            )
