from dataclasses import dataclass

from forex_agent.domain._guards import require_revision_sequence
from forex_agent.domain.forecast_performance_benchmark_comparison import (
    ForecastPerformanceBenchmarkComparison,
)
from forex_agent.domain.forecast_performance_categorical_summary import (
    ForecastPerformanceCategoricalSummary,
)
from forex_agent.domain.forecast_performance_exclusion_reason import (
    ForecastPerformanceExclusionReason,
)
from forex_agent.domain.forecast_performance_numeric_summary import (
    ForecastPerformanceNumericSummary,
)
from forex_agent.domain.forecast_performance_sample_diagnostics import (
    ForecastPerformanceSampleDiagnostics,
)
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class ForecastPerformanceSnapshotMember:
    """FX-66 Section 15: the EXACT evidence basis for one accepted
    cohort member -- pins every vintage reference by key+revision,
    never a mutable display field (Section 6's own "do not
    reconstruct selection from current mutable display fields")."""

    evaluation_key: str
    evaluation_revision_sequence: int
    forecast_claim_key: str
    forecast_revision_sequence: int
    outcome_key: str
    outcome_revision_sequence: int

    def __post_init__(self) -> None:
        for name, value in (
            ("evaluation_key", self.evaluation_key),
            ("forecast_claim_key", self.forecast_claim_key),
            ("outcome_key", self.outcome_key),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string, got {value!r}")
        require_revision_sequence(self.evaluation_revision_sequence)
        require_revision_sequence(self.forecast_revision_sequence)
        require_revision_sequence(self.outcome_revision_sequence)


@dataclass(frozen=True, slots=True)
class ForecastPerformanceSnapshot:
    """FX-66 Section 15: ONE immutable, append-only performance
    calculation -- `(snapshot_key, revision_sequence)` is the row's
    own identity, mirroring every other FX-62/64/65 vintage type
    exactly. `knowledge_cutoff` is the PIT bound the population was
    BUILT against (the historical-input-cutoff timeline); `availability`
    is FTA's own instant of actually RECORDING this snapshot (the
    separate recording-availability timeline, Section 15's own
    explicit distinction) -- a snapshot is never backdated to the
    historical period it studies.

    Carries its own COMPLETE evidence basis -- exact member
    references, exact exclusions with reasons, both summary shapes
    (whichever applies), the benchmark comparison, and full sample
    diagnostics -- so full-history determinism (Section 16) can
    compare the COMPLETE payload, never only a headline metric."""

    snapshot_key: str
    revision_sequence: int
    methodology_key: str
    methodology_version_sequence: int
    cohort_key: str
    cohort_version_sequence: int
    evaluation_mode: ForecastProvenanceMode
    members: tuple[ForecastPerformanceSnapshotMember, ...]
    exclusions: tuple[tuple[str, ForecastPerformanceExclusionReason], ...]
    benchmark_comparison: ForecastPerformanceBenchmarkComparison
    diagnostics: ForecastPerformanceSampleDiagnostics
    knowledge_cutoff: UtcTimestamp
    availability: UtcTimestamp
    algorithm_version: str
    numeric_summary: ForecastPerformanceNumericSummary | None = None
    categorical_summary: ForecastPerformanceCategoricalSummary | None = None
    correction_reason: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("snapshot_key", self.snapshot_key),
            ("methodology_key", self.methodology_key),
            ("cohort_key", self.cohort_key),
            ("algorithm_version", self.algorithm_version),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string, got {value!r}")
        require_revision_sequence(self.revision_sequence)
        require_revision_sequence(self.methodology_version_sequence)
        require_revision_sequence(self.cohort_version_sequence)
        if not isinstance(self.evaluation_mode, ForecastProvenanceMode):
            raise TypeError(
                f"evaluation_mode must be a ForecastProvenanceMode, got "
                f"{type(self.evaluation_mode).__name__}"
            )
        for member in self.members:
            if not isinstance(member, ForecastPerformanceSnapshotMember):
                raise TypeError(
                    "every members entry must be a ForecastPerformanceSnapshotMember, got "
                    f"{type(member).__name__}"
                )
        for evaluation_key, reason in self.exclusions:
            if not isinstance(evaluation_key, str) or not evaluation_key.strip():
                raise ValueError(
                    f"exclusion evaluation_key must be non-empty, got {evaluation_key!r}"
                )
            if not isinstance(reason, ForecastPerformanceExclusionReason):
                raise TypeError(
                    f"exclusion reason must be a ForecastPerformanceExclusionReason, got "
                    f"{type(reason).__name__}"
                )
        if not isinstance(self.benchmark_comparison, ForecastPerformanceBenchmarkComparison):
            raise TypeError(
                "benchmark_comparison must be a ForecastPerformanceBenchmarkComparison, got "
                f"{type(self.benchmark_comparison).__name__}"
            )
        if not isinstance(self.diagnostics, ForecastPerformanceSampleDiagnostics):
            raise TypeError(
                f"diagnostics must be a ForecastPerformanceSampleDiagnostics, got "
                f"{type(self.diagnostics).__name__}"
            )
        for name, ts in (
            ("knowledge_cutoff", self.knowledge_cutoff),
            ("availability", self.availability),
        ):
            if not isinstance(ts, UtcTimestamp):
                raise TypeError(f"{name} must be a UtcTimestamp, got {type(ts).__name__}")
        if self.correction_reason is not None and (
            not isinstance(self.correction_reason, str) or not self.correction_reason.strip()
        ):
            raise ValueError(
                f"correction_reason must be a non-empty string or None, got "
                f"{self.correction_reason!r}"
            )

        if len(self.members) != self.diagnostics.accepted_count:
            raise ValueError(
                f"len(members) ({len(self.members)}) must equal diagnostics.accepted_count "
                f"({self.diagnostics.accepted_count})"
            )
        if len(self.exclusions) != sum(count for _, count in self.diagnostics.excluded_by_reason):
            raise ValueError("len(exclusions) must equal the sum of diagnostics.excluded_by_reason")
        if self.numeric_summary is not None and self.categorical_summary is not None:
            raise ValueError("numeric_summary and categorical_summary must not both be populated")
        if self.numeric_summary is not None and self.numeric_summary.n != len(self.members):
            raise ValueError("numeric_summary.n must equal len(members)")
        if self.categorical_summary is not None and self.categorical_summary.n != len(self.members):
            raise ValueError("categorical_summary.n must equal len(members)")
