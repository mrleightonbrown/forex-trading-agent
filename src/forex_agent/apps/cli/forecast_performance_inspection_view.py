"""FX-67 Section 15: pure builder converting an already-fetched
`ForecastPerformanceInspection` (plus optional members/exclusions/
benchmark pages, already fetched by the caller) into a JSON-safe
`dict[str, object]` -- the "structured inspection output" this story
requires, suitable for a CLI's `--json` flag, a future API route, or
a future dashboard. No I/O, no repository access, no recomputation of
any metric (mirrors `apps.api.view_models.news_evidence_view_model`'s
own "pure builder over already-fetched evidence" convention exactly).

Every `UtcTimestamp` becomes its own ISO-8601 string; every `Decimal`
becomes its own string (never a `float` -- CLAUDE.md, and Section 9's
own "preserve exact units" rule); every enum becomes its own `.value`.
A missing value stays `None` -- never replaced with `0` or omitted
(Section 5's own "Missing values" rule)."""

from decimal import Decimal

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
from forex_agent.domain.timestamps import UtcTimestamp


def _ts(value: UtcTimestamp | None) -> str | None:
    return value.value.isoformat() if value is not None else None


def _dec(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _unresolved(ref: UnresolvedEvidenceReference) -> dict[str, object]:
    return {
        "integrity_diagnostic": True,
        "what": ref.what,
        "key": ref.key,
        "revision_sequence": ref.revision_sequence,
    }


def _originator_view(originator: ResolvedOriginatorIdentity | None) -> dict[str, object] | None:
    if originator is None:
        return None
    attribution = originator.attribution
    return {
        "attribution_kind": attribution.kind.value,
        "publisher_source_key": attribution.publisher_source_key,
        "publisher_display_name": originator.publisher_display_name,
        "forecaster_source_key": attribution.forecaster_source_key,
        "forecaster_display_name": originator.forecaster_display_name,
        "anonymous_respondent_id": attribution.anonymous_respondent_id,
    }


def build_forecast_performance_inspection_view(
    inspection: ForecastPerformanceInspection,
    *,
    members: ForecastPerformanceMemberPage | None = None,
    exclusions: ForecastPerformanceExclusionPage | None = None,
    benchmark_inspection: ForecastPerformanceBenchmarkInspection | None = None,
    revision_inspection: ForecastPerformanceRevisionInspection | None = None,
) -> dict[str, object]:
    snapshot = inspection.snapshot
    diagnostics = snapshot.diagnostics
    numeric = snapshot.numeric_summary
    categorical = snapshot.categorical_summary

    view: dict[str, object] = {
        "identity_and_scope": {
            "snapshot_key": snapshot.snapshot_key,
            "revision_sequence": snapshot.revision_sequence,
            "mode": inspection.mode.value,
            "evaluation_mode": snapshot.evaluation_mode.value,
            "knowledge_cutoff": _ts(snapshot.knowledge_cutoff),
            "availability": _ts(snapshot.availability),
            "algorithm_version": snapshot.algorithm_version,
            "cohort_key": snapshot.cohort_key,
            "cohort_version_sequence": snapshot.cohort_version_sequence,
            "methodology_key": snapshot.methodology_key,
            "methodology_version_sequence": snapshot.methodology_version_sequence,
            "cohort_resolved": inspection.cohort is not None,
            "methodology_resolved": inspection.methodology is not None,
            "target_key": inspection.target.target_key if inspection.target else None,
            "target_variable_name": inspection.target.variable_name if inspection.target else None,
            "target_unit": inspection.target.unit if inspection.target else None,
            "horizon_category": inspection.cohort.horizon_category if inspection.cohort else None,
            "issue_window_start": (
                _ts(inspection.cohort.issue_window_start) if inspection.cohort else None
            ),
            "issue_window_end": (
                _ts(inspection.cohort.issue_window_end) if inspection.cohort else None
            ),
            "protocol_key": inspection.protocol.protocol_key if inspection.protocol else None,
            "protocol_version_sequence": (
                inspection.protocol.version_sequence if inspection.protocol else None
            ),
            "outcome_vintage_selection_policy": (
                inspection.protocol.outcome_vintage_selection_policy.value
                if inspection.protocol
                else None
            ),
        },
        "counts": {
            "raw_candidate_count": diagnostics.raw_candidate_count,
            "accepted_count": diagnostics.accepted_count,
            "excluded_count": diagnostics.raw_candidate_count - diagnostics.accepted_count,
            "distinct_target_period_count": diagnostics.distinct_target_period_count,
            "unique_target_event_count": diagnostics.unique_target_event_count,
            "unique_forecast_issue_count": diagnostics.unique_forecast_issue_count,
            "production_count": diagnostics.production_count,
            "research_count": diagnostics.research_count,
        },
        "metrics": {
            "numeric": (
                {
                    "n": numeric.n,
                    "unit": numeric.unit,
                    "mean_absolute_error": _dec(numeric.mean_absolute_error),
                    "mean_signed_error": _dec(numeric.mean_signed_error),
                    "root_mean_squared_error": _dec(numeric.root_mean_squared_error),
                }
                if numeric is not None
                else None
            ),
            "categorical": (
                {
                    "n": categorical.n,
                    "match_count": categorical.match_count,
                    "mismatch_count": categorical.mismatch_count,
                    "accuracy": _dec(categorical.accuracy),
                    "confusion_counts": [list(t) for t in categorical.confusion_counts],
                    "realized_class_distribution": list(categorical.realized_class_distribution),
                }
                if categorical is not None
                else None
            ),
        },
        "evidence_sufficiency": {
            "sample_adequacy": inspection.limitations.sample_adequacy.value,
            "sample_adequacy_explanation": inspection.limitations.sample_adequacy_explanation,
        },
        "limitations": list(inspection.limitations.limitations),
        "attribution": _originator_view(inspection.originator),
    }

    if benchmark_inspection is not None:
        comparison = benchmark_inspection.comparison
        benchmark = benchmark_inspection.benchmark
        view["benchmark"] = {
            "status": comparison.status.value,
            "benchmark_key": comparison.benchmark_key,
            "benchmark_version_sequence": comparison.benchmark_version_sequence,
            "benchmark_kind": benchmark.kind.value if benchmark is not None else None,
            "benchmark_unresolved": benchmark_inspection.benchmark_unresolved,
            "paired_count": comparison.paired_count,
            "is_complete_pairing": benchmark_inspection.is_complete_pairing,
            "source_mean_absolute_error": _dec(comparison.source_mean_absolute_error),
            "benchmark_mean_absolute_error": _dec(comparison.benchmark_mean_absolute_error),
            "mean_absolute_error_difference": _dec(comparison.mean_absolute_error_difference),
            "relative_mae_improvement": _dec(comparison.relative_mae_improvement),
            "source_accuracy": _dec(comparison.source_accuracy),
            "benchmark_accuracy": _dec(comparison.benchmark_accuracy),
            "accuracy_difference": _dec(comparison.accuracy_difference),
        }

    if members is not None:
        view["members"] = {
            "next_cursor": members.next_cursor,
            "items": [_member_view(m) for m in members.members],
        }

    if exclusions is not None:
        view["exclusions"] = {
            "next_cursor": exclusions.next_cursor,
            "excluded_by_reason": [
                {"reason": reason.value, "count": count}
                for reason, count in exclusions.excluded_by_reason
            ],
            "items": [
                {"evaluation_key": key, "reason": reason.value}
                for key, reason in exclusions.exclusions
            ],
        }

    if revision_inspection is not None:
        view["administrative_revision_inspection"] = {
            "historical_cutoff": _ts(revision_inspection.report.historical_cutoff),
            "administrative_as_of": _ts(revision_inspection.report.administrative_as_of),
            "pending_evaluation_keys": list(revision_inspection.report.pending_evaluation_keys),
        }

    return view


def _member_view(
    member: ForecastEvaluationInspection | UnresolvedEvidenceReference,
) -> dict[str, object]:
    if isinstance(member, UnresolvedEvidenceReference):
        return _unresolved(member)

    evaluation = member.evaluation
    result = evaluation.result
    forecast_view: dict[str, object]
    if isinstance(member.forecast_vintage, UnresolvedEvidenceReference):
        forecast_view = _unresolved(member.forecast_vintage)
    else:
        forecast = member.forecast_vintage
        forecast_view = {
            "claim_key": forecast.claim_key,
            "revision_sequence": forecast.revision_sequence,
            "availability": _ts(forecast.availability),
            "original_publication_at": _ts(forecast.original_publication_at),
            "provenance_mode": forecast.provenance_mode.value,
            "numeric_value": _dec(forecast.numeric_value),
            "unit": forecast.unit,
            "categorical_outcome": forecast.categorical_outcome,
        }

    outcome_view: dict[str, object]
    if isinstance(member.outcome_vintage, UnresolvedEvidenceReference):
        outcome_view = _unresolved(member.outcome_vintage)
    else:
        outcome = member.outcome_vintage
        outcome_view = {
            "outcome_key": outcome.outcome_key,
            "revision_sequence": outcome.revision_sequence,
            "availability": _ts(outcome.availability),
            "provenance_mode": outcome.provenance_mode.value,
            "numeric_value": _dec(outcome.numeric_value),
            "unit": outcome.unit,
            "categorical_outcome": outcome.categorical_outcome,
            "authentication_reviewed_by": outcome.authentication_review.reviewed_by,
            "authentication_review_method": outcome.authentication_review.review_method,
            "authentication_reviewed_at": _ts(outcome.authentication_review.reviewed_at),
        }

    return {
        "evaluation_key": evaluation.evaluation_key,
        "revision_sequence": evaluation.revision_sequence,
        "availability": _ts(evaluation.availability),
        "evaluation_mode": evaluation.evaluation_mode.value,
        "signed_error": _dec(result.signed_error),
        "absolute_error": _dec(result.absolute_error),
        "unit": result.unit,
        "categorical_result": (
            result.categorical_result.value if result.categorical_result is not None else None
        ),
        "forecast_authentication_reviewed_by": (
            evaluation.forecast_authentication_review.reviewed_by
        ),
        "forecast": forecast_view,
        "outcome": outcome_view,
        "originator": _originator_view(member.originator),
    }
