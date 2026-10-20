"""FX-67 Section 15: a plain-text, analyst-facing rendering of an
already-fetched `ForecastPerformanceInspection` (plus optional
members/exclusions/benchmark/revision pages) -- the "human-readable
inspection output" this story requires. Organized into the NINE
numbered parts Section 15 itself specifies, in order. No I/O; this is
a pure function of already-fetched data, exactly like `forecast_
performance_inspection_view.build_forecast_performance_inspection_view`
(the SAME inputs feed both renderings -- one data-fetch, two
presentations, mirroring `apps.api.routers.market_context`'s own "one
code path builds both the JSON route and the HTML page" discipline).

Deliberately NO leaderboard, rating, percentage bar, or any other
decorative credibility indicator (Section 15's own explicit
prohibition) -- every number here is printed as plain text, with its
own unit, next to the evidence that produced it."""

from forex_agent.application.use_cases.forecast_performance_inspection_support import (
    UnresolvedEvidenceReference,
)
from forex_agent.application.use_cases.get_forecast_evaluation_inspection import (
    ForecastEvaluationInspection,
    ResolvedOriginatorIdentity,
)
from forex_agent.application.use_cases.get_forecast_performance_benchmark_inspection import (
    ForecastPerformanceBenchmarkInspection,
)
from forex_agent.application.use_cases.get_forecast_performance_exclusions import (
    ForecastPerformanceExclusionPage,
)
from forex_agent.application.use_cases.get_forecast_performance_inspection import (
    ForecastPerformanceInspection,
)
from forex_agent.application.use_cases.get_forecast_performance_members import (
    ForecastPerformanceMemberPage,
)
from forex_agent.application.use_cases.get_forecast_performance_revision_inspection import (
    ForecastPerformanceRevisionInspection,
)
from forex_agent.domain.forecast_performance_benchmark_comparison_status import (
    ForecastPerformanceBenchmarkComparisonStatus,
)


def _display_name(originator: ResolvedOriginatorIdentity | None) -> str:
    if originator is None:
        return "(originator unresolved)"
    attribution = originator.attribution
    kind = attribution.kind.value
    publisher = (
        originator.publisher_display_name
        or f"unresolved identity ({attribution.publisher_source_key})"
    )
    if kind == "NAMED_INSTITUTION":
        forecaster = originator.forecaster_display_name or (
            f"unresolved identity ({attribution.forecaster_source_key})"
        )
        return f"{forecaster} (institutional forecast, published via {publisher})"
    if kind == "AGGREGATE_SURVEY_CONSENSUS":
        return f"aggregate survey consensus, published by {publisher}"
    pseudonym = attribution.anonymous_respondent_id
    return f"anonymous respondent{f' ({pseudonym})' if pseudonym else ''}, surveyed by {publisher}"


def render_forecast_performance_inspection_report(
    inspection: ForecastPerformanceInspection,
    *,
    members: ForecastPerformanceMemberPage | None = None,
    exclusions: ForecastPerformanceExclusionPage | None = None,
    benchmark_inspection: ForecastPerformanceBenchmarkInspection | None = None,
    revision_inspection: ForecastPerformanceRevisionInspection | None = None,
) -> str:
    snapshot = inspection.snapshot
    diagnostics = snapshot.diagnostics
    lines: list[str] = []

    # 1. Snapshot identity and scope.
    lines.append(f"=== Forecast Performance Inspection: {snapshot.snapshot_key} ===")
    lines.append(
        f"Mode: {inspection.mode.value}  "
        f"(snapshot evaluation_mode={snapshot.evaluation_mode.value})"
    )
    lines.append(
        f"Revision: {snapshot.revision_sequence}  "
        f"Algorithm/policy version: {snapshot.algorithm_version}"
    )
    lines.append(
        f"Knowledge cutoff (historical input cutoff being analyzed): "
        f"{snapshot.knowledge_cutoff.value.isoformat()}"
    )
    lines.append(
        f"Snapshot recording availability (when FTA actually recorded this): "
        f"{snapshot.availability.value.isoformat()}"
    )
    lines.append(f"Cohort: {snapshot.cohort_key} v{snapshot.cohort_version_sequence}")
    lines.append(
        f"Methodology: {snapshot.methodology_key} v{snapshot.methodology_version_sequence}"
    )
    if inspection.cohort is None:
        lines.append("  INTEGRITY DIAGNOSTIC: the pinned cohort version could not be resolved.")
    else:
        lines.append(
            f"  Target: {inspection.cohort.target_key}"
            + (
                f" ({inspection.target.variable_name}, unit={inspection.target.unit})"
                if inspection.target is not None
                else ""
            )
        )
        lines.append(f"  Declared horizon category: {inspection.cohort.horizon_category!r}")
        window_start = (
            inspection.cohort.issue_window_start.value.isoformat()
            if inspection.cohort.issue_window_start
            else "(none)"
        )
        window_end = (
            inspection.cohort.issue_window_end.value.isoformat()
            if inspection.cohort.issue_window_end
            else "(none)"
        )
        lines.append(f"  Issue window: {window_start} .. {window_end}")
    if inspection.protocol is not None:
        policy = inspection.protocol.outcome_vintage_selection_policy.value
        lines.append(
            f"  Evaluation protocol: {inspection.protocol.protocol_key} "
            f"v{inspection.protocol.version_sequence} (outcome-vintage policy: {policy})"
        )
    excluded_count = diagnostics.raw_candidate_count - diagnostics.accepted_count
    lines.append(
        f"Raw candidates: {diagnostics.raw_candidate_count}  "
        f"Accepted: {diagnostics.accepted_count}  Excluded: {excluded_count}"
    )
    lines.append(
        f"Distinct target periods: {diagnostics.distinct_target_period_count}  "
        f"Distinct outcome events: {diagnostics.unique_target_event_count}"
    )

    # 2. Performance metrics.
    lines.append("")
    lines.append("--- Performance metrics (exact stored values; never recalculated here) ---")
    if snapshot.numeric_summary is not None:
        n = snapshot.numeric_summary
        lines.append(
            f"MAE={n.mean_absolute_error}{n.unit}  "
            f"mean signed error={n.mean_signed_error}{n.unit}  "
            f"RMSE={n.root_mean_squared_error}{n.unit}  (n={n.n})"
        )
    elif snapshot.categorical_summary is not None:
        c = snapshot.categorical_summary
        lines.append(
            f"Matches={c.match_count}  Mismatches={c.mismatch_count}  "
            f"Accuracy={c.accuracy} (n={c.n})"
        )
        lines.append(f"Confusion counts (predicted, observed, count): {list(c.confusion_counts)}")
        lines.append(f"Realized outcome distribution: {list(c.realized_class_distribution)}")
    else:
        lines.append("No numeric or categorical summary is available for this snapshot.")

    # 3. Evidence sufficiency.
    lines.append("")
    lines.append("--- Evidence sufficiency ---")
    lines.append(inspection.limitations.sample_adequacy_explanation)

    # 4. Benchmark result.
    lines.append("")
    lines.append("--- Benchmark ---")
    if benchmark_inspection is None:
        lines.append(
            f"Status: {snapshot.benchmark_comparison.status.value} (not independently inspected)"
        )
    elif (
        benchmark_inspection.comparison.status
        is ForecastPerformanceBenchmarkComparisonStatus.BENCHMARK_UNAVAILABLE
    ):
        lines.append("BENCHMARK_UNAVAILABLE -- no benchmark comparison applies to this snapshot.")
    else:
        comparison = benchmark_inspection.comparison
        benchmark = benchmark_inspection.benchmark
        lines.append(
            f"Benchmark: {comparison.benchmark_key} v{comparison.benchmark_version_sequence}"
            + (
                f" ({benchmark.kind.value})"
                if benchmark is not None
                else " (UNRESOLVED -- integrity gap)"
            )
        )
        lines.append(
            f"Paired observations: {comparison.paired_count}  "
            f"Complete pairing: {benchmark_inspection.is_complete_pairing}"
        )
        if comparison.source_mean_absolute_error is not None:
            lines.append(
                f"Source MAE={comparison.source_mean_absolute_error}  "
                f"Benchmark MAE={comparison.benchmark_mean_absolute_error}  "
                f"Difference={comparison.mean_absolute_error_difference}"
            )
        if comparison.source_accuracy is not None:
            lines.append(
                f"Source accuracy={comparison.source_accuracy}  "
                f"Benchmark accuracy={comparison.benchmark_accuracy}  "
                f"Difference={comparison.accuracy_difference}"
            )

    # 5. Accepted member listing.
    lines.append("")
    lines.append("--- Accepted members ---")
    if members is None:
        lines.append("(not requested)")
    elif not members.members:
        lines.append("(no accepted members)")
    else:
        for member in members.members:
            lines.append(_render_member_line(member))
        if members.next_cursor is not None:
            lines.append(f"(more members available -- next cursor: {members.next_cursor!r})")

    # 6. Exclusions.
    lines.append("")
    lines.append("--- Exclusions ---")
    if exclusions is None:
        lines.append("(not requested)")
    elif not exclusions.exclusions:
        lines.append("(no excluded candidates)")
    else:
        for key, reason in exclusions.exclusions:
            lines.append(f"  {key}: {reason.value}")
        if exclusions.next_cursor is not None:
            lines.append(f"(more exclusions available -- next cursor: {exclusions.next_cursor!r})")

    # 7. Source attribution.
    lines.append("")
    lines.append("--- Source attribution ---")
    lines.append(f"Cohort-level originator: {_display_name(inspection.originator)}")

    # 8. Availability / provenance.
    lines.append("")
    lines.append("--- Availability / provenance ---")
    provenance_label = (
        "Production-observed"
        if snapshot.evaluation_mode.value == "PRODUCTION_OBSERVED"
        else "Retrospective research"
    )
    lines.append(f"{provenance_label} evidence, inspected in {inspection.mode.value} mode.")
    lines.append(f"Historical knowledge cutoff: {snapshot.knowledge_cutoff.value.isoformat()}")
    lines.append(f"Snapshot recording availability: {snapshot.availability.value.isoformat()}")
    if revision_inspection is not None:
        report = revision_inspection.report
        pending = list(report.pending_evaluation_keys) if report.pending_evaluation_keys else "none"
        lines.append(
            f"Administrative revision inspection "
            f"(as of {report.administrative_as_of.value.isoformat()}): "
            f"{len(report.pending_evaluation_keys)} pending revision(s) known since the "
            f"historical cutoff -- {pending}. This is purely administrative and does not "
            "alter the frozen snapshot above."
        )

    # 9. Limitations.
    lines.append("")
    lines.append("--- Limitations ---")
    for limitation in inspection.limitations.limitations:
        lines.append(f"  - {limitation}")

    return "\n".join(lines)


def _render_member_line(member: ForecastEvaluationInspection | UnresolvedEvidenceReference) -> str:
    if isinstance(member, UnresolvedEvidenceReference):
        return (
            f"  INTEGRITY DIAGNOSTIC: {member.what} ({member.key!r}, "
            f"revision {member.revision_sequence}) could not be resolved."
        )
    evaluation = member.evaluation
    result = evaluation.result
    if isinstance(member.forecast_vintage, UnresolvedEvidenceReference) or isinstance(
        member.outcome_vintage, UnresolvedEvidenceReference
    ):
        missing = []
        if isinstance(member.forecast_vintage, UnresolvedEvidenceReference):
            missing.append("forecast")
        if isinstance(member.outcome_vintage, UnresolvedEvidenceReference):
            missing.append("outcome")
        joined = ", ".join(missing)
        return (
            f"  {evaluation.evaluation_key}: INTEGRITY DIAGNOSTIC -- unresolved {joined} evidence."
        )

    forecast = member.forecast_vintage
    outcome = member.outcome_vintage
    originator = _display_name(member.originator)
    if result.signed_error is not None:
        value_line = (
            f"forecast={forecast.numeric_value}{forecast.unit} observed={outcome.numeric_value}"
            f"{outcome.unit} signed_error={result.signed_error}{result.unit} "
            f"absolute_error={result.absolute_error}{result.unit}"
        )
    else:
        value_line = (
            f"forecast={forecast.categorical_outcome} observed={outcome.categorical_outcome} "
            f"result={result.categorical_result.value if result.categorical_result else None}"
        )
    return (
        f"  {evaluation.evaluation_key} (rev {evaluation.revision_sequence}): {value_line} | "
        f"originator: {originator} | provenance: {evaluation.evaluation_mode.value} | "
        f"evaluation availability: {evaluation.availability.value.isoformat()}"
    )
