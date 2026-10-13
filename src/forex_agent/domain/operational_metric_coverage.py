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
    not UNAVAILABLE, once the underlying evidence is known complete.
    **FX-63H Section H2**: for acquisition metrics specifically, this
    value is reserved for a FUTURE complete-coverage contract (e.g. an
    explicit instrumentation-liveness record) and is never emitted by
    `GetSourceOperationalProfileAsOf` today -- the mere existence of a
    recorded attempt before a window's own `window_start` does NOT
    prove the window was continuously instrumented, since this
    codebase has no heartbeat/liveness signal, only discrete attempt
    events. Content metrics (derived from FX-56/57's own always-
    complete `NewsItem` evidence) are unaffected and continue to use
    `OBSERVED` normally."""

    PARTIAL = "PARTIAL"
    """Some relevant observation history exists, but completeness over
    the full requested window is not established -- e.g. at least one
    acquisition attempt was recorded somewhere within the window,
    without any guarantee the window was exhaustively instrumented
    throughout."""

    UNAVAILABLE = "UNAVAILABLE"
    """Required observations do not exist, or cannot be resolved, for
    this metric over this window -- never silently reported as a zero
    or a 0% rate."""

    NOT_APPLICABLE = "NOT_APPLICABLE"
    """This metric does not apply to the available source configuration
    at all (e.g. no source-native evidence exists for this technical
    source_key under any window)."""
