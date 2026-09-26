from enum import Enum


class AvailabilityConfidence(Enum):
    """How strongly a vintage's `availability` timestamp is evidenced
    (FX-51 Section 13 -- "backfills must not break PIT").

    This is the economic-event analog of `domain.release_timing_rule.
    ReleaseTimingConfidence` (FX-44), generalized with a third state
    that model does not have: `ReleaseTimingConfidence` only ever
    describes a timestamp someone HAS derived (from a documented
    institutional rule) -- it has no "we have no idea" member because
    a `ReleaseTimingRule` is only ever constructed when a rule exists.
    FX-51 explicitly needs a genuine "we don't know" state (a historical
    backfill whose real-world availability was never established by
    its source), so `UNKNOWN` is a first-class member here, not merely
    the absence of a rule.

    - VERIFIED: `availability` is a confirmed knowability instant --
      a primary-source publication timestamp, or an equivalently
      strong confirmation. The strongest claim; safe for point-in-time
      research use.
    - ESTIMATED: `availability` is a deliberately conservative,
      research-safe bound (mirrors `ReleaseTimingConfidence.
      CONSERVATIVE_SAFE_BOUND`) -- not the exact confirmed instant, but
      chosen to be guaranteed no earlier than the true (unknown-exact)
      availability. Also safe for point-in-time research use, but must
      never be presented as `VERIFIED`.
    - UNKNOWN: no defensible availability instant exists at all.
      `availability` MUST be `None` whenever this is set (FX-51 Section
      13: "do not silently substitute ingestion time for historical
      publication time") -- a PIT query must fail closed / return
      UNAVAILABLE for any vintage in this state, never treat it as
      visible at any `as_of`, however far in the future.
    """

    VERIFIED = "VERIFIED"
    ESTIMATED = "ESTIMATED"
    UNKNOWN = "UNKNOWN"
