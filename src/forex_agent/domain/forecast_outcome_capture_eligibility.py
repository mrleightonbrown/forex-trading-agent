from enum import Enum


class ForecastOutcomeCaptureEligibility(Enum):
    """FX-65 Section 5: capture eligibility for ONE raw outcome
    candidate -- a STRUCTURAL check only, mirroring FX-64's own
    `ForecastCaptureEligibility` and its FX-64H-clarified boundary
    exactly: `ELIGIBLE` never implies independent authentication of
    the underlying evidence, only that the candidate's own fields
    assemble into a well-formed `ForecastOutcomeVintage`."""

    ELIGIBLE = "ELIGIBLE"

    INSUFFICIENT_SPECIFICATION = "INSUFFICIENT_SPECIFICATION"
    """The candidate's own target period or payload shape is missing,
    malformed, or internally inconsistent."""

    UNVERIFIED_EVIDENCE = "UNVERIFIED_EVIDENCE"
    """The candidate's own supporting evidence reference OR its
    required `EvidenceAuthenticationReview` is missing or structurally
    invalid."""
