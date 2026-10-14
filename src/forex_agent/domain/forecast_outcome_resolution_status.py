from enum import Enum


class ForecastOutcomeResolutionStatus(Enum):
    """FX-65 Section 5: the result of attempting to resolve ONE
    outcome at a PIT instant under an evaluation protocol's own
    vintage-selection policy. Absence of an outcome is NEVER
    represented as a fabricated zero value -- these four states are
    the only way an unresolved outcome is ever reported."""

    NOT_YET_MATURED = "NOT_YET_MATURED"
    """This outcome is known to FTA (at least one vintage has been
    recorded for it, at some point), but no vintage qualifies at the
    requested PIT instant under the requested policy -- a forecast
    whose horizon has not completed is not incorrect."""

    OUTCOME_UNAVAILABLE = "OUTCOME_UNAVAILABLE"
    """This outcome has never been recorded at all, under any
    provenance mode or at any instant -- a coverage gap, never
    inferred to mean the forecast was wrong."""

    OUTCOME_AMBIGUOUS = "OUTCOME_AMBIGUOUS"
    """The requested selection policy cannot be resolved to one
    unambiguous vintage (e.g. `FIXED_RELEASE_VINTAGE` with no pinned
    revision configured) -- a configuration defect, surfaced rather
    than guessed at."""

    OUTCOME_AVAILABLE = "OUTCOME_AVAILABLE"
    """Exactly one outcome vintage was resolved under the requested
    policy and PIT instant."""
