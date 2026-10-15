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
    """Too few unique target events (or zero accepted members) to
    describe even a basic distribution of outcomes."""

    DESCRIPTIVE_ONLY = "DESCRIPTIVE_ONLY"
    """Enough members to report descriptive metrics (MAE, accuracy,
    ...) honestly, but NOT enough -- or not independent/clean enough
    (overlapping events, mixed research/production, or research-only
    provenance, which Section 13 says can never support inference
    regardless of count) -- to support any comparative or inferential
    claim."""

    COMPARABLE_SAMPLE = "COMPARABLE_SAMPLE"
    """A genuinely comparable, production-observed population large
    enough to support benchmark-relative DESCRIPTIVE comparison, but
    still short of the inference threshold."""

    INFERENCE_SUPPORTED = "INFERENCE_SUPPORTED"
    """Large enough, clean enough, and production-observed -- the ONLY
    tier where a bounded statistical-uncertainty calculation (Section
    12) is methodologically defensible. Still never implies
    `SKILLED`/`TRUSTWORTHY`/any inferential verdict by itself."""
