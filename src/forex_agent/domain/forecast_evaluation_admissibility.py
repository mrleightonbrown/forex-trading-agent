from enum import Enum


class ForecastEvaluationAdmissibility(Enum):
    """FX-65 Section 8: whether ONE forecast vintage can actually be
    evaluated under a given protocol and PIT instant -- a DISTINCT,
    stricter question than FX-64's own `ForecastCaptureEligibility`.
    A structurally valid, capture-eligible forecast is not
    automatically admissible for evaluation (this story's own core
    principle). A non-`ADMISSIBLE` verdict means no evaluation is ever
    persisted -- mirrors FX-64's own "a rejected candidate is never
    persisted" rule exactly."""

    ADMISSIBLE = "ADMISSIBLE"

    UNVERIFIED_SOURCE = "UNVERIFIED_SOURCE"
    """No `EvidenceAuthenticationReview` was supplied for the forecast
    being evaluated. A syntactically valid evidence reference alone
    (FX-64H's own boundary) never satisfies this -- an explicit, human,
    out-of-band review record is required."""

    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    """An `EvidenceAuthenticationReview` was supplied, but it carries
    no independent corroboration reference -- a single-sourced human
    attestation, weaker than `UNVERIFIED_SOURCE`'s total absence but
    still short of this story's own evidentiary bar for an admissible
    evaluation."""

    AMBIGUOUS_TARGET = "AMBIGUOUS_TARGET"
    """The forecast's own `target_period` does not EXACTLY match the
    resolved outcome's own `target_period` -- never evaluated under a
    merely similar period."""

    PROTOCOL_MISMATCH = "PROTOCOL_MISMATCH"
    """The forecast's own `forecast_type`/`target_key` does not match
    what the evaluation protocol is defined for."""

    NOT_YET_MATURED = "NOT_YET_MATURED"
    """The outcome's own horizon has not yet completed as of the
    requested instant -- see `ForecastOutcomeResolutionStatus.
    NOT_YET_MATURED`."""

    OUTCOME_UNAVAILABLE = "OUTCOME_UNAVAILABLE"
    """No outcome could be resolved at all (never recorded, or the
    protocol's own selection policy could not be resolved
    unambiguously) -- see `ForecastOutcomeResolutionStatus.OUTCOME_
    UNAVAILABLE`/`OUTCOME_AMBIGUOUS`, both folded into this single
    admissibility verdict."""

    RESEARCH_ONLY = "RESEARCH_ONLY"
    """The forecast is admissible for a RETROSPECTIVE_RESEARCH
    evaluation only -- a PRODUCTION_OBSERVED evaluation was requested,
    but the forecast's own vintage is itself `RETROSPECTIVE_RESEARCH`,
    so treating it as contemporaneously evaluable in production would
    misrepresent when FTA actually knew it."""
