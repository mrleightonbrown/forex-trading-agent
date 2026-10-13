from enum import Enum


class ForecastCaptureEligibility(Enum):
    """FX-64 Section 11: CAPTURE eligibility states -- never outcome
    states. Nothing here says a forecast was "correct," "incorrect,"
    "successful," or "failed" (that is FX-65's own future job,
    explicitly out of scope here). A non-`ELIGIBLE` verdict means the
    candidate is rejected/quarantined and MUST NOT be persisted as a
    confirmed, evaluable forecast."""

    ELIGIBLE = "ELIGIBLE"
    INSUFFICIENT_SPECIFICATION = "INSUFFICIENT_SPECIFICATION"
    """The candidate's own target definition, target period, unit, or
    statistical convention is missing, unsupported, or materially
    ambiguous -- e.g. an unadmitted `target_key`, or a target period
    kind that does not match its own target definition's own `period_
    frequency`."""

    AMBIGUOUS_ATTRIBUTION = "AMBIGUOUS_ATTRIBUTION"
    """The candidate cannot establish a structurally valid, non-
    conflated attribution (Section 8) -- e.g. a named forecaster
    identity alongside an aggregate-consensus attribution kind."""

    UNSUPPORTED_FORECAST_TYPE = "UNSUPPORTED_FORECAST_TYPE"
    """The candidate is not one of the two admitted forecast classes
    (Section 4) -- e.g. a directional, probabilistic, or threshold
    statement with no exact value or closed categorical outcome."""

    UNVERIFIED_EVIDENCE = "UNVERIFIED_EVIDENCE"
    """The candidate's own supporting evidence reference is missing,
    structurally invalid, or insufficiently specific to audit (Section
    6) -- e.g. no document identifier at all for an external-document
    reference."""
