from enum import Enum


class ForecastPerformanceBenchmarkComparisonStatus(Enum):
    """FX-66 Section 11: whether a benchmark-relative comparison was
    actually possible -- "a missing benchmark is not a reason to
    fabricate a comparison" (Section 11's own explicit rule), so
    `BENCHMARK_UNAVAILABLE` is a first-class, expected result, never
    an error."""

    COMPARED = "COMPARED"
    """A paired, compatible benchmark population existed and the
    comparison was computed."""

    BENCHMARK_UNAVAILABLE = "BENCHMARK_UNAVAILABLE"
    """No benchmark was pinned by the methodology, or the pinned
    benchmark had zero paired observations against this population --
    absolute descriptive performance is still reported elsewhere; no
    comparison is fabricated."""
