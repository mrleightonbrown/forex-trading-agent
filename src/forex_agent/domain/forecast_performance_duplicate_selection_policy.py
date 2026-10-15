from enum import Enum


class ForecastPerformanceDuplicateSelectionPolicy(Enum):
    """FX-66 Section 7: HOW a cohort resolves multiple forecast issues
    (distinct `claim_key`s) from the SAME originator, targeting the
    SAME outcome event, at the SAME `horizon_category` -- a defensible
    policy must be fixed BEFORE realized errors are known, never
    chosen afterward to flatter a result.

    Only ONE concrete policy is implemented for `fx66_v1`, deliberately
    (Section 7 itself only REQUIRES "an explicit choice," not every
    conceivable one) -- a fixed-lead-time policy is deferred until a
    real population actually needs it."""

    EARLIEST_QUALIFYING_ISSUE = "EARLIEST_QUALIFYING_ISSUE"
    """Among forecast issues tied for the same originator/outcome
    event/horizon_category, keep only the one whose own forecast
    vintage reports the EARLIEST `availability` -- every other tied
    issue is excluded as `SUPERSEDED_BY_EARLIER_QUALIFYING_ISSUE`.
    Never "the latest before the outcome," which Section 7 explicitly
    forbids (that would select issues BECAUSE they are closer to the
    realized value)."""
