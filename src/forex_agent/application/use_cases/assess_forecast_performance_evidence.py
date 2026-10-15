"""FX-66 Section 8: `AssessForecastPerformanceEvidence` -- reports
sample adequacy, overlap, missingness, and selection limitations for
an already-built population. Deliberately SYNCHRONOUS/pure (no
repository access): every fact it needs is already attached to each
`ForecastPerformancePopulationMember` by `BuildForecastPerformance
PopulationAsOf`, so this use case is a plain aggregation over data
already in hand -- distinct target PERIODS are counted from each
member's own resolved `outcome_vintage.target_period` directly (a
frozen, hashable value object), never a separate repository round-
trip.

**Sample-adequacy classification is a FIXED, documented rule**
(Section 8's own "do not set arbitrary significance thresholds
merely to produce PASS results"), never a configurable methodology
parameter a caller could tune to flatter a result. `RETROSPECTIVE_
RESEARCH` populations are capped at `DESCRIPTIVE_ONLY` regardless of
size (Section 13's own "a retrospective corpus must never imply the
system could have acted on it").

**FX-66H (H2) correction -- `INFERENCE_SUPPORTED` is never emitted.**
The original rule promoted to `INFERENCE_SUPPORTED` purely from
`accepted_count`, which let 30+ accepted forecasts automatically be
labelled suitable for statistical inference regardless of
independence, benchmark pairing, uncertainty, or selection bias --
and regardless of how many of those accepted forecasts actually
targeted DISTINCT real-world events (`accepted_count` can be large
while `distinct_target_period_count` stays small, e.g. several
outcome DEFINITIONS all keyed to the SAME underlying meeting/period).
`fx66_v1` now gates on `distinct_target_period_count` -- the most
conservative of the available uniqueness diagnostics -- and caps at
`COMPARABLE_SAMPLE`: compatible observations exist for DESCRIPTIVE
comparison; this certifies neither statistical independence nor
forecasting skill. `INFERENCE_SUPPORTED` remains defined on `Forecast
PerformanceSampleAdequacy` ONLY for forward compatibility -- reserved,
and never emitted by this version's own classification rule.

**FX-66H.1 (F66-04) correction -- `pending_revision_count` is retired
from active computation.** It previously derived from `population.
pending_revision_evaluation_keys`, which required an UNBOUNDED
repository read that leaked future knowledge into an otherwise PIT-
reproducible historical result (fixed in `BuildForecastPerformance
PopulationAsOf`'s own module docstring). That field no longer exists
on `ForecastPerformancePopulation`, so this diagnostic is now always
`0` -- a historically reproducible constant, never a future-looking
value. The real diagnostic this used to carry now lives entirely in
the separate, explicitly-administrative `InspectForecastPerformance
PendingRevisions` use case, which is never consulted here and never
persisted as part of any snapshot."""

from dataclasses import dataclass
from decimal import Decimal

from forex_agent.application.use_cases.build_forecast_performance_population_as_of import (
    ForecastPerformancePopulation,
)
from forex_agent.domain.forecast_performance_exclusion_reason import (
    ForecastPerformanceExclusionReason,
)
from forex_agent.domain.forecast_performance_sample_adequacy import (
    ForecastPerformanceSampleAdequacy,
)
from forex_agent.domain.forecast_performance_sample_diagnostics import (
    ForecastPerformanceSampleDiagnostics,
)
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.timestamps import UtcTimestamp

_INSUFFICIENT_BELOW = 5
_COMPARABLE_AT_LEAST = 20


def _classify_sample_adequacy(
    accepted_count: int,
    distinct_target_period_count: int,
    evaluation_mode: ForecastProvenanceMode,
) -> ForecastPerformanceSampleAdequacy:
    """FX-66H (H2): gated on `distinct_target_period_count`, NOT
    `accepted_count` alone -- the latter can be inflated by multiple
    outcome definitions all keyed to the SAME underlying real-world
    period, which `distinct_target_period_count` catches and
    `accepted_count`/`unique_target_event_count` would not. Capped at
    `COMPARABLE_SAMPLE`; `INFERENCE_SUPPORTED` is never returned by
    this rule (see module docstring)."""
    if accepted_count < _INSUFFICIENT_BELOW or distinct_target_period_count < _INSUFFICIENT_BELOW:
        return ForecastPerformanceSampleAdequacy.INSUFFICIENT_DATA
    if evaluation_mode is ForecastProvenanceMode.RETROSPECTIVE_RESEARCH:
        return ForecastPerformanceSampleAdequacy.DESCRIPTIVE_ONLY
    if distinct_target_period_count < _COMPARABLE_AT_LEAST:
        return ForecastPerformanceSampleAdequacy.DESCRIPTIVE_ONLY
    return ForecastPerformanceSampleAdequacy.COMPARABLE_SAMPLE


@dataclass(frozen=True, slots=True)
class _Span:
    earliest: UtcTimestamp | None
    latest: UtcTimestamp | None


def _evaluation_availability_span(
    population: ForecastPerformancePopulation,
) -> _Span:
    if not population.accepted:
        return _Span(None, None)
    timestamps = [m.evaluation.availability for m in population.accepted]
    return _Span(min(timestamps, key=lambda ts: ts.value), max(timestamps, key=lambda ts: ts.value))


class AssessForecastPerformanceEvidence:
    def __call__(
        self, population: ForecastPerformancePopulation, *, benchmark_paired_count: int = 0
    ) -> ForecastPerformanceSampleDiagnostics:
        accepted = population.accepted
        accepted_count = len(accepted)

        excluded_counts: dict[ForecastPerformanceExclusionReason, int] = {}
        for _, reason in population.exclusions:
            excluded_counts[reason] = excluded_counts.get(reason, 0) + 1

        unique_forecast_issue_count = len({m.evaluation.forecast_claim_key for m in accepted})
        unique_target_event_count = len({m.evaluation.outcome_key for m in accepted})
        distinct_target_period_count = len({m.outcome_vintage.target_period for m in accepted})

        production_count = sum(
            1
            for m in accepted
            if m.evaluation.evaluation_mode is ForecastProvenanceMode.PRODUCTION_OBSERVED
        )
        research_count = accepted_count - production_count

        missing_outcome_count = excluded_counts.get(
            ForecastPerformanceExclusionReason.MISSING_OR_UNRESOLVED_OUTCOME, 0
        )
        missing_outcome_rate = (
            Decimal(missing_outcome_count) / Decimal(population.raw_candidate_count)
            if population.raw_candidate_count > 0
            else Decimal(0)
        )

        span = _evaluation_availability_span(population)
        sample_adequacy = _classify_sample_adequacy(
            accepted_count, distinct_target_period_count, population.cohort.evaluation_mode
        )

        return ForecastPerformanceSampleDiagnostics(
            raw_candidate_count=population.raw_candidate_count,
            accepted_count=accepted_count,
            excluded_by_reason=tuple(
                sorted(excluded_counts.items(), key=lambda pair: pair[0].value)
            ),
            unique_forecast_issue_count=unique_forecast_issue_count,
            unique_target_event_count=unique_target_event_count,
            distinct_target_period_count=distinct_target_period_count,
            benchmark_paired_count=benchmark_paired_count,
            production_count=production_count,
            research_count=research_count,
            missing_outcome_rate=missing_outcome_rate,
            earliest_availability=span.earliest,
            latest_availability=span.latest,
            sample_adequacy=sample_adequacy,
        )
