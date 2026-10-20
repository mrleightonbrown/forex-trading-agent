"""FX-67 Section 11: `GetForecastPerformanceLimitations` -- a PURE,
read-only derivation (no repository access, mirroring `AssessForecast
PerformanceEvidence`/`CalculateForecastPerformance`'s own "already-
built-population in, no I/O" convention) over a snapshot's own
already-computed `diagnostics`/`cohort`/`benchmark_comparison`/
`evaluation_mode` -- NEVER a fresh judgment call; every limitation
below is derived deterministically from facts the snapshot already
carries.

This is this story's single most load-bearing module: Section 11 is
explicit that `COMPARABLE_SAMPLE` never means demonstrated skill, and
that the forecast-horizon limitation below "must remain visible for
historical performance reports" -- so the horizon sentence and the
three other STANDING disclosures are returned on EVERY call,
unconditionally, never gated on sample size or adequacy tier."""

from dataclasses import dataclass

from forex_agent.domain.forecast_attribution_kind import ForecastAttributionKind
from forex_agent.domain.forecast_performance_benchmark_comparison import (
    ForecastPerformanceBenchmarkComparison,
)
from forex_agent.domain.forecast_performance_benchmark_comparison_status import (
    ForecastPerformanceBenchmarkComparisonStatus,
)
from forex_agent.domain.forecast_performance_sample_adequacy import (
    ForecastPerformanceSampleAdequacy,
)
from forex_agent.domain.forecast_performance_sample_diagnostics import (
    ForecastPerformanceSampleDiagnostics,
)
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode

#: Section 11's own exact required sentence -- verbatim, never
#: paraphrased, since the story names this precise wording.
HORIZON_LIMITATION = "Forecast horizon comparability has not been independently verified."

_ARCHIVE_COMPLETENESS_LIMITATION = (
    "This source's archive is not assumed to be complete -- forecasts that exist but were "
    "never captured by FTA cannot appear in this population, and their absence is not evidence "
    "of anything."
)
_NO_INFERENCE_LIMITATION = (
    "fx66_v1 supports no approved statistical-inference methodology -- no sample size, however "
    "large, establishes forecasting skill under this methodology."
)
_AUTHENTICATION_REVIEW_LIMITATION = (
    "Evidence authentication review records who reviewed the evidence, how, and when -- it is "
    "not independent proof that the underlying document is genuine."
)

_SAMPLE_ADEQUACY_EXPLANATION: dict[ForecastPerformanceSampleAdequacy, str] = {
    ForecastPerformanceSampleAdequacy.INSUFFICIENT_DATA: (
        "INSUFFICIENT_DATA: too few accepted forecasts, or too few distinct target periods, to "
        "describe even a basic distribution of outcomes."
    ),
    ForecastPerformanceSampleAdequacy.DESCRIPTIVE_ONLY: (
        "DESCRIPTIVE_ONLY: enough evidence to report descriptive metrics honestly, but not "
        "enough -- or not independent/clean enough -- to support any comparative claim."
    ),
    ForecastPerformanceSampleAdequacy.COMPARABLE_SAMPLE: (
        "COMPARABLE_SAMPLE: compatible observations exist for descriptive benchmark comparison "
        "only. This does NOT mean forecasting skill has been demonstrated, and does not certify "
        "statistical independence."
    ),
    ForecastPerformanceSampleAdequacy.INFERENCE_SUPPORTED: (
        "INFERENCE_SUPPORTED is reserved for forward compatibility and is never emitted by "
        "fx66_v1 -- its presence here would itself be a defect."
    ),
}


@dataclass(frozen=True, slots=True)
class ForecastPerformanceLimitations:
    sample_adequacy: ForecastPerformanceSampleAdequacy
    sample_adequacy_explanation: str
    limitations: tuple[str, ...]


class GetForecastPerformanceLimitations:
    def __call__(
        self,
        diagnostics: ForecastPerformanceSampleDiagnostics,
        attribution_kind: ForecastAttributionKind | None,
        benchmark_comparison: ForecastPerformanceBenchmarkComparison,
        evaluation_mode: ForecastProvenanceMode,
    ) -> ForecastPerformanceLimitations:
        """`attribution_kind` is `None` only on an integrity gap (the
        cohort that would name it could not be resolved) -- in that
        case the anonymous-respondent limitation below is simply
        skipped, rather than guessing a kind via a fabricated cohort
        object (Section 6's own "do not invent replacement data"
        rule, applied here too)."""
        limitations: list[str] = []

        if diagnostics.accepted_count > 0:
            limitations.append(
                "Statistical independence among accepted observations is unknown and has not "
                "been verified."
            )
        if diagnostics.distinct_target_period_count < diagnostics.unique_target_event_count:
            limitations.append(
                f"{diagnostics.unique_target_event_count} distinct outcome event(s) correspond "
                f"to only {diagnostics.distinct_target_period_count} distinct real-world target "
                "period(s) -- multiple outcome definitions share at least one underlying period."
            )
        if (
            benchmark_comparison.status
            is ForecastPerformanceBenchmarkComparisonStatus.BENCHMARK_UNAVAILABLE
        ):
            limitations.append("No benchmark comparison is available for this snapshot.")
        elif (
            benchmark_comparison.status is ForecastPerformanceBenchmarkComparisonStatus.COMPARED
            and diagnostics.accepted_count > 0
            and benchmark_comparison.paired_count < diagnostics.accepted_count
        ):
            limitations.append(
                f"Benchmark pairing is incomplete: only {benchmark_comparison.paired_count} of "
                f"{diagnostics.accepted_count} accepted observation(s) have a paired benchmark "
                "value."
            )
        if evaluation_mode is ForecastProvenanceMode.RETROSPECTIVE_RESEARCH:
            limitations.append(
                "This is a RETROSPECTIVE RESEARCH result: forecasts were recovered and "
                "authenticated after their original publication, carrying retrospective-"
                "selection risk FTA could not have acted on contemporaneously."
            )
            limitations.append(
                "This evidence is research-only -- it must not be presented as production "
                "forecasting history."
            )
        if attribution_kind is ForecastAttributionKind.ANONYMOUS_RESPONDENT:
            limitations.append(
                "This cohort's originator is an anonymous respondent -- no named forecaster "
                "identity exists or is ever assigned."
            )

        limitations.append(_ARCHIVE_COMPLETENESS_LIMITATION)
        limitations.append(_AUTHENTICATION_REVIEW_LIMITATION)
        limitations.append(HORIZON_LIMITATION)
        limitations.append(_NO_INFERENCE_LIMITATION)

        return ForecastPerformanceLimitations(
            sample_adequacy=diagnostics.sample_adequacy,
            sample_adequacy_explanation=_SAMPLE_ADEQUACY_EXPLANATION[diagnostics.sample_adequacy],
            limitations=tuple(limitations),
        )
