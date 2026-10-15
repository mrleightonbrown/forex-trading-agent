from enum import Enum


class ForecastPerformanceMissingDataPolicy(Enum):
    """FX-66 Section 9/14: HOW a missing observation (no resolved
    outcome, no paired benchmark) affects a metric's own denominator
    -- a methodology binding, not a configurable risk. Only ONE value
    is implemented for `fx66_v1`, deliberately: Section 9's own
    "never interpret missing observations as zero-error predictions"
    is an absolute rule, not a choice, so no OTHER policy value exists
    to select by mistake."""

    EXCLUDE_FROM_DENOMINATOR = "EXCLUDE_FROM_DENOMINATOR"
    """A missing value is excluded from BOTH the numerator and the
    denominator of every metric it would otherwise contribute to --
    never counted as a zero error, a match, or a mismatch."""
