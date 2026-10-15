from enum import Enum


class ForecastPerformanceSampleAdequacy(Enum):
    """FX-66 Section 8: an evidence-READINESS classification -- NEVER
    an evaluation of whether a forecaster is good or bad (the
    architect's own explicit distinction). Classified by `AssessForecast
    PerformanceEvidence` from a FIXED, documented rule (Section 8's own
    "do not set arbitrary significance thresholds merely to produce
    PASS results"), never a configurable, tunable threshold a
    methodology could select to flatter a result."""

    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    """Too few accepted members, or too few DISTINCT target periods
    (the more conservative of the two uniqueness diagnostics -- see
    `distinct_target_period_count`), to describe even a basic
    distribution of outcomes."""

    DESCRIPTIVE_ONLY = "DESCRIPTIVE_ONLY"
    """Enough members to report descriptive metrics (MAE, accuracy,
    ...) honestly, but NOT enough -- or not independent/clean enough
    (overlapping events, mixed research/production, or research-only
    provenance, which Section 13 says can never support inference
    regardless of count) -- to support any comparative or inferential
    claim."""

    COMPARABLE_SAMPLE = "COMPARABLE_SAMPLE"
    """A genuinely comparable, production-observed population large
    enough (by `distinct_target_period_count`, the most conservative
    available uniqueness diagnostic -- never `accepted_count` alone)
    to support benchmark-relative DESCRIPTIVE comparison. This is the
    CEILING `fx66_v1` ever assigns -- it certifies neither statistical
    independence nor forecasting skill, and must never be read as
    "large enough for inference" (FX-66H's own H2 correction: sample
    SIZE alone, even 30 or 100 accepted observations, previously
    promoted to `INFERENCE_SUPPORTED` below regardless of
    independence, benchmark pairing, uncertainty, or selection bias)."""

    INFERENCE_SUPPORTED = "INFERENCE_SUPPORTED"
    """RESERVED for forward compatibility ONLY -- `fx66_v1`'s own
    classification rule (`AssessForecastPerformanceEvidence`) NEVER
    returns this value (FX-66H's own H2 correction). A future version
    may emit it only once a separately authorized, genuinely
    independence-aware inference contract exists; until then, no
    sample size by itself justifies it. Still never implies
    `SKILLED`/`TRUSTWORTHY`/any inferential verdict by itself even if
    a future version does emit it."""
