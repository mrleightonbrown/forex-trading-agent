from enum import Enum


class OperationalMetricCoverage(Enum):
    """FX-63 Section 8.4: how well a SPECIFIC metric on a `Source
    OperationalProfile` is actually supported by recorded observations
    -- always metric-specific, never a single blanket judgment about a
    source's "whole" operational history. A profile with excellent
    content-history coverage may simultaneously have zero acquisition-
    reliability coverage, and both must be reported honestly, side by
    side, never merged into one overall label."""

    OBSERVED = "OBSERVED"
    """Supported by available recorded evidence for the stated metric
    -- a genuine zero (e.g. "zero withdrawals observed") is OBSERVED,
    not UNAVAILABLE, once the underlying evidence is known complete."""

    PARTIAL = "PARTIAL"
    """Some relevant observation history exists, but completeness over
    the full requested window is not established -- e.g. acquisition
    instrumentation started partway through the requested window."""

    UNAVAILABLE = "UNAVAILABLE"
    """Required observations do not exist, or cannot be resolved, for
    this metric over this window -- never silently reported as a zero
    or a 0% rate."""

    NOT_APPLICABLE = "NOT_APPLICABLE"
    """This metric does not apply to the available source configuration
    at all (e.g. no source-native evidence exists for this technical
    source_key under any window)."""
