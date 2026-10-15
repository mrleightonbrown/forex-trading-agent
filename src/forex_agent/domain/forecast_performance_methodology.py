from dataclasses import dataclass

from forex_agent.domain._guards import require_revision_sequence
from forex_agent.domain.forecast_performance_missing_data_policy import (
    ForecastPerformanceMissingDataPolicy,
)
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class ForecastPerformanceMethodology:
    """FX-66 Section 14: ONE append-only version of an immutable
    methodology, binding HOW a pinned cohort's own population is
    calculated and interpreted -- `(methodology_key, version_sequence)`
    is the row's own identity. A correction is a NEW, higher `version_
    sequence` row, never a mutation (Section 14's own "never revise
    historical methodology in place" rule); the SAME cohort evaluated
    under two different methodology versions produces two separately
    identifiable snapshots (Section 14's own explicit requirement).

    Deliberately narrow: `cohort_key`/`cohort_version_sequence` pin
    ONE cohort's own eligibility rules (Section 4 already owns those);
    this type adds only what Section 4 does NOT -- an OPTIONAL
    benchmark pin, the missing-data policy, and `algorithm_version`
    (the audit trail for the EXACT calculation/classification logic
    used, mirroring every other `algorithm_version` in this codebase
    -- Section 8's own fixed sample-adequacy rule is versioned through
    THIS field, never through a tunable methodology parameter)."""

    methodology_key: str
    version_sequence: int
    cohort_key: str
    cohort_version_sequence: int
    missing_data_policy: ForecastPerformanceMissingDataPolicy
    algorithm_version: str
    availability: UtcTimestamp
    rationale: str
    benchmark_key: str | None = None
    benchmark_version_sequence: int | None = None
    correction_reason: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("methodology_key", self.methodology_key),
            ("cohort_key", self.cohort_key),
            ("algorithm_version", self.algorithm_version),
            ("rationale", self.rationale),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string, got {value!r}")
        require_revision_sequence(self.version_sequence)
        require_revision_sequence(self.cohort_version_sequence)
        if not isinstance(self.missing_data_policy, ForecastPerformanceMissingDataPolicy):
            raise TypeError(
                "missing_data_policy must be a ForecastPerformanceMissingDataPolicy, got "
                f"{type(self.missing_data_policy).__name__}"
            )
        if not isinstance(self.availability, UtcTimestamp):
            raise TypeError(
                f"availability must be a UtcTimestamp, got {type(self.availability).__name__}"
            )
        if self.correction_reason is not None and (
            not isinstance(self.correction_reason, str) or not self.correction_reason.strip()
        ):
            raise ValueError(
                f"correction_reason must be a non-empty string or None, got "
                f"{self.correction_reason!r}"
            )

        if self.benchmark_key is None and self.benchmark_version_sequence is None:
            return
        if not isinstance(self.benchmark_key, str) or not self.benchmark_key.strip():
            raise ValueError(
                "benchmark_key must be a non-empty string when benchmark_version_sequence is set"
            )
        require_revision_sequence(self.benchmark_version_sequence)
