from dataclasses import dataclass
from decimal import Decimal

from forex_agent.domain.forecast_performance_exclusion_reason import (
    ForecastPerformanceExclusionReason,
)
from forex_agent.domain.forecast_performance_sample_adequacy import (
    ForecastPerformanceSampleAdequacy,
)
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class ForecastPerformanceSampleDiagnostics:
    """FX-66 Section 8: every REQUIRED evidence-sufficiency diagnostic,
    bundled as one immutable record so a snapshot's own evidence basis
    is always reported in full, never reduced to a headline number
    (Section 16's own "do not compare only the headline figure" rule,
    applied here too)."""

    raw_candidate_count: int
    accepted_count: int
    excluded_by_reason: tuple[tuple[ForecastPerformanceExclusionReason, int], ...]
    unique_forecast_issue_count: int
    unique_target_event_count: int
    distinct_target_period_count: int
    benchmark_paired_count: int
    production_count: int
    research_count: int
    missing_outcome_rate: Decimal
    earliest_availability: UtcTimestamp | None
    latest_availability: UtcTimestamp | None
    sample_adequacy: ForecastPerformanceSampleAdequacy

    def __post_init__(self) -> None:
        for name, value in (
            ("raw_candidate_count", self.raw_candidate_count),
            ("accepted_count", self.accepted_count),
            ("unique_forecast_issue_count", self.unique_forecast_issue_count),
            ("unique_target_event_count", self.unique_target_event_count),
            ("distinct_target_period_count", self.distinct_target_period_count),
            ("benchmark_paired_count", self.benchmark_paired_count),
            ("production_count", self.production_count),
            ("research_count", self.research_count),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative int, got {value!r}")
        if self.accepted_count > self.raw_candidate_count:
            raise ValueError("accepted_count must not exceed raw_candidate_count")
        if sum(count for _, count in self.excluded_by_reason) + self.accepted_count != (
            self.raw_candidate_count
        ):
            raise ValueError(
                "excluded_by_reason counts plus accepted_count must equal raw_candidate_count"
            )
        if self.production_count + self.research_count != self.accepted_count:
            raise ValueError("production_count + research_count must equal accepted_count")
        if not isinstance(self.missing_outcome_rate, Decimal):
            raise TypeError(
                "missing_outcome_rate must be a Decimal, got "
                f"{type(self.missing_outcome_rate).__name__}"
            )
        if not (Decimal("0") <= self.missing_outcome_rate <= Decimal("1")):
            raise ValueError(
                f"missing_outcome_rate must be between 0 and 1, got {self.missing_outcome_rate}"
            )
        for name, ts in (
            ("earliest_availability", self.earliest_availability),
            ("latest_availability", self.latest_availability),
        ):
            if ts is not None and not isinstance(ts, UtcTimestamp):
                raise TypeError(f"{name} must be a UtcTimestamp or None, got {type(ts).__name__}")
        if self.accepted_count == 0 and (
            self.earliest_availability is not None or self.latest_availability is not None
        ):
            raise ValueError(
                "earliest_availability/latest_availability must be None when accepted_count is 0"
            )
        if self.accepted_count > 0 and (
            self.earliest_availability is None or self.latest_availability is None
        ):
            raise ValueError(
                "earliest_availability/latest_availability are required when accepted_count > 0"
            )
        if not isinstance(self.sample_adequacy, ForecastPerformanceSampleAdequacy):
            raise TypeError(
                "sample_adequacy must be a ForecastPerformanceSampleAdequacy, got "
                f"{type(self.sample_adequacy).__name__}"
            )
