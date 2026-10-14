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
    reference.

    **FX-64H (H2) boundary, stated explicitly because this name invites
    the opposite reading**: this is a STRUCTURAL check only. `ELIGIBLE`
    (the absence of this verdict) NEVER means the referenced document
    was independently authenticated -- that a human actually confirmed
    it exists, is genuine, or says what is claimed. No code in this
    story fetches, hashes, or cross-references a cited document; a
    syntactically well-formed but entirely fabricated `document_
    identifier` is, correctly, still `ELIGIBLE`. Authenticating a
    source is a human, out-of-band responsibility exercised BEFORE a
    candidate is ever constructed (e.g. by whoever curates a pilot
    import); it is deliberately not, and does not become, this
    enum's job."""
