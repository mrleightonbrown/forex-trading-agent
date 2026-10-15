"""FX-66 Section 20.A-F: synthetic-fixture tests for the full
`BuildForecastPerformancePopulationAsOf` -> `AssessForecastPerformance
Evidence` -> `CalculateForecastPerformance` pipeline, against FAKE
repositories seeded with hand-built domain objects (bypassing the
FX-64/65 capture use cases entirely -- this story consumes already-
existing evaluation evidence, never produces it). All data here is
SYNTHETIC and labelled as such; see `test_forecast_performance_real_
pilot.py` for the one real-data demonstration (Dataset A)."""

from datetime import UTC, datetime
from decimal import Decimal

from forex_agent.application.use_cases.assess_forecast_performance_evidence import (
    AssessForecastPerformanceEvidence,
)
from forex_agent.application.use_cases.build_forecast_performance_population_as_of import (
    BuildForecastPerformancePopulationAsOf,
)
from forex_agent.application.use_cases.calculate_forecast_performance import (
    CalculateForecastPerformance,
)
from forex_agent.domain.categorical_evaluation_result import CategoricalEvaluationResult
from forex_agent.domain.evidence_authentication_review import EvidenceAuthenticationReview
from forex_agent.domain.forecast_attribution import ForecastAttribution
from forex_agent.domain.forecast_attribution_kind import ForecastAttributionKind
from forex_agent.domain.forecast_evaluation_metric import ForecastEvaluationMetric
from forex_agent.domain.forecast_evaluation_result import ForecastEvaluationResult
from forex_agent.domain.forecast_evidence_kind import ForecastEvidenceKind
from forex_agent.domain.forecast_evidence_reference import ForecastEvidenceReference
from forex_agent.domain.forecast_outcome_vintage import ForecastOutcomeVintage
from forex_agent.domain.forecast_performance_benchmark_comparison_status import (
    ForecastPerformanceBenchmarkComparisonStatus,
)
from forex_agent.domain.forecast_performance_benchmark_definition import (
    ForecastPerformanceBenchmarkDefinition,
)
from forex_agent.domain.forecast_performance_benchmark_kind import (
    ForecastPerformanceBenchmarkKind,
)
from forex_agent.domain.forecast_performance_cohort_definition import (
    ForecastPerformanceCohortDefinition,
)
from forex_agent.domain.forecast_performance_duplicate_selection_policy import (
    ForecastPerformanceDuplicateSelectionPolicy,
)
from forex_agent.domain.forecast_performance_exclusion_reason import (
    ForecastPerformanceExclusionReason,
)
from forex_agent.domain.forecast_performance_sample_adequacy import (
    ForecastPerformanceSampleAdequacy,
)
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.forecast_target_period import ForecastTargetPeriod
from forex_agent.domain.forecast_target_period_kind import ForecastTargetPeriodKind
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.structured_forecast_evaluation_vintage import (
    StructuredForecastEvaluationVintage,
)
from forex_agent.domain.structured_forecast_vintage import StructuredForecastVintage
from forex_agent.domain.timestamps import UtcTimestamp
from tests.fakes.forecast_evaluation_repository import FakeForecastEvaluationRepository
from tests.fakes.forecast_outcome_repository import FakeForecastOutcomeRepository
from tests.fakes.structured_forecast_repository import FakeStructuredForecastRepository

_PUBLISHER = "__fx66_test_publisher__"
_FORECASTER = "__fx66_test_forecaster__"
_NUMERIC_TARGET = "CA_POLICY_RATE_LEVEL_AFTER_MEETING"
_OTHER_NUMERIC_TARGET = "US_REAL_GDP_GROWTH_QOQ_SAAR"
_CATEGORICAL_TARGET = "CA_POLICY_RATE_DECISION_HIKE_HOLD_CUT"
_DEFINITION_KEY = "__fx66_test_def__"
_PROTOCOL_KEY = "__fx66_test_protocol__"


def _ts(hour: int, day: int = 1) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, day, hour, tzinfo=UTC))


def _period(meeting_id: str) -> ForecastTargetPeriod:
    return ForecastTargetPeriod(
        period_kind=ForecastTargetPeriodKind.POLICY_MEETING, policy_meeting_identifier=meeting_id
    )


def _attribution(**overrides: object) -> ForecastAttribution:
    defaults: dict[str, object] = {
        "kind": ForecastAttributionKind.AGGREGATE_SURVEY_CONSENSUS,
        "publisher_source_key": _PUBLISHER,
    }
    defaults.update(overrides)
    return ForecastAttribution(**defaults)  # type: ignore[arg-type]


def _evidence(doc_id: str) -> ForecastEvidenceReference:
    return ForecastEvidenceReference(
        evidence_kind=ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
        description="synthetic test evidence",
        document_identifier=doc_id,
    )


def _review(reviewed_at: UtcTimestamp) -> EvidenceAuthenticationReview:
    return EvidenceAuthenticationReview(
        reviewed_by="tester", review_method="synthetic", reviewed_at=reviewed_at
    )


def _numeric_forecast(
    claim_key: str,
    meeting_id: str,
    numeric_value: Decimal,
    availability: UtcTimestamp,
    *,
    original_publication_at: UtcTimestamp | None = None,
    attribution: ForecastAttribution | None = None,
    target_key: str = _NUMERIC_TARGET,
) -> StructuredForecastVintage:
    return StructuredForecastVintage(
        claim_key=claim_key,
        revision_sequence=0,
        availability=availability,
        algorithm_version="fx66_test_v1",
        forecast_type=ForecastType.NUMERIC_POINT,
        target_key=target_key,
        target_period=_period(meeting_id),
        attribution=attribution or _attribution(),
        provenance_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        evidence=_evidence(f"{claim_key}-doc"),
        numeric_value=numeric_value,
        unit="PERCENT",
        original_publication_at=original_publication_at,
    )


def _categorical_forecast(
    claim_key: str,
    meeting_id: str,
    categorical_outcome: str,
    availability: UtcTimestamp,
    *,
    attribution: ForecastAttribution | None = None,
) -> StructuredForecastVintage:
    return StructuredForecastVintage(
        claim_key=claim_key,
        revision_sequence=0,
        availability=availability,
        algorithm_version="fx66_test_v1",
        forecast_type=ForecastType.CATEGORICAL_EVENT,
        target_key=_CATEGORICAL_TARGET,
        target_period=_period(meeting_id),
        attribution=attribution or _attribution(),
        provenance_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        evidence=_evidence(f"{claim_key}-doc"),
        categorical_outcome=categorical_outcome,
    )


def _numeric_outcome(
    outcome_key: str,
    meeting_id: str,
    numeric_value: Decimal,
    availability: UtcTimestamp,
    *,
    definition_key: str = _DEFINITION_KEY,
) -> ForecastOutcomeVintage:
    return ForecastOutcomeVintage(
        outcome_key=outcome_key,
        revision_sequence=0,
        definition_key=definition_key,
        definition_version_sequence=0,
        availability=availability,
        target_period=_period(meeting_id),
        outcome_type=ForecastType.NUMERIC_POINT,
        evidence=_evidence(f"{outcome_key}-doc"),
        authentication_review=_review(availability),
        provenance_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        numeric_value=numeric_value,
        unit="PERCENT",
    )


def _categorical_outcome(
    outcome_key: str,
    meeting_id: str,
    categorical_outcome: str,
    availability: UtcTimestamp,
    *,
    definition_key: str = f"{_DEFINITION_KEY}-cat",
) -> ForecastOutcomeVintage:
    return ForecastOutcomeVintage(
        outcome_key=outcome_key,
        revision_sequence=0,
        definition_key=definition_key,
        definition_version_sequence=0,
        availability=availability,
        target_period=_period(meeting_id),
        outcome_type=ForecastType.CATEGORICAL_EVENT,
        evidence=_evidence(f"{outcome_key}-doc"),
        authentication_review=_review(availability),
        provenance_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        categorical_outcome=categorical_outcome,
    )


def _numeric_evaluation(
    evaluation_key: str,
    claim_key: str,
    outcome_key: str,
    signed_error: Decimal,
    availability: UtcTimestamp,
    *,
    protocol_key: str = _PROTOCOL_KEY,
    protocol_version: int = 0,
    definition_key: str = _DEFINITION_KEY,
    mode: ForecastProvenanceMode = ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
) -> StructuredForecastEvaluationVintage:
    return StructuredForecastEvaluationVintage(
        evaluation_key=evaluation_key,
        revision_sequence=0,
        forecast_claim_key=claim_key,
        forecast_revision_sequence=0,
        protocol_key=protocol_key,
        protocol_version_sequence=protocol_version,
        outcome_definition_key=definition_key,
        outcome_definition_version_sequence=0,
        outcome_key=outcome_key,
        outcome_revision_sequence=0,
        evaluation_mode=mode,
        algorithm_version="fx65_v1",
        availability=availability,
        result=ForecastEvaluationResult(
            metric=ForecastEvaluationMetric.NUMERIC_ERROR,
            signed_error=signed_error,
            absolute_error=abs(signed_error),
            unit="PERCENT",
        ),
        forecast_authentication_review=_review(availability),
    )


def _categorical_evaluation(
    evaluation_key: str,
    claim_key: str,
    outcome_key: str,
    result: CategoricalEvaluationResult,
    availability: UtcTimestamp,
    *,
    protocol_key: str = _PROTOCOL_KEY,
    protocol_version: int = 0,
    definition_key: str = f"{_DEFINITION_KEY}-cat",
    mode: ForecastProvenanceMode = ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
) -> StructuredForecastEvaluationVintage:
    return StructuredForecastEvaluationVintage(
        evaluation_key=evaluation_key,
        revision_sequence=0,
        forecast_claim_key=claim_key,
        forecast_revision_sequence=0,
        protocol_key=protocol_key,
        protocol_version_sequence=protocol_version,
        outcome_definition_key=definition_key,
        outcome_definition_version_sequence=0,
        outcome_key=outcome_key,
        outcome_revision_sequence=0,
        evaluation_mode=mode,
        algorithm_version="fx65_v1",
        availability=availability,
        result=ForecastEvaluationResult(
            metric=ForecastEvaluationMetric.CATEGORICAL_MATCH, categorical_result=result
        ),
        forecast_authentication_review=_review(availability),
    )


def _cohort(**overrides: object) -> ForecastPerformanceCohortDefinition:
    defaults: dict[str, object] = {
        "cohort_key": "__fx66_test_cohort__",
        "version_sequence": 0,
        "attribution_kind": ForecastAttributionKind.AGGREGATE_SURVEY_CONSENSUS,
        "originator_publisher_source_key": _PUBLISHER,
        "target_key": _NUMERIC_TARGET,
        "forecast_type": ForecastType.NUMERIC_POINT,
        "horizon_category": "SAME-MEETING",
        "protocol_key": _PROTOCOL_KEY,
        "protocol_version_sequence": 0,
        "evaluation_mode": ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        "duplicate_selection_policy": (
            ForecastPerformanceDuplicateSelectionPolicy.EARLIEST_QUALIFYING_ISSUE
        ),
        "availability": _ts(9),
        "rationale": "synthetic test cohort",
    }
    defaults.update(overrides)
    return ForecastPerformanceCohortDefinition(**defaults)  # type: ignore[arg-type]


class _Repos:
    def __init__(self) -> None:
        self.forecast = FakeStructuredForecastRepository()
        self.outcome = FakeForecastOutcomeRepository()
        self.evaluation = FakeForecastEvaluationRepository()

    def seed(
        self,
        claim_key: str,
        meeting_id: str,
        outcome_key: str,
        evaluation_key: str,
        forecast_value: Decimal,
        observed_value: Decimal,
        *,
        availability: UtcTimestamp | None = None,
        forecast_availability: UtcTimestamp | None = None,
        original_publication_at: UtcTimestamp | None = None,
        mode: ForecastProvenanceMode = ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
    ) -> None:
        availability = availability or _ts(12)
        self.forecast.vintages[claim_key] = [
            _numeric_forecast(
                claim_key,
                meeting_id,
                forecast_value,
                forecast_availability or availability,
                original_publication_at=original_publication_at,
            )
        ]
        self.outcome.vintages[outcome_key] = [
            _numeric_outcome(outcome_key, meeting_id, observed_value, availability)
        ]
        self.evaluation.vintages[evaluation_key] = [
            _numeric_evaluation(
                evaluation_key,
                claim_key,
                outcome_key,
                observed_value - forecast_value,
                availability,
                mode=mode,
            )
        ]

    def builder(self) -> BuildForecastPerformancePopulationAsOf:
        return BuildForecastPerformancePopulationAsOf(self.evaluation, self.forecast, self.outcome)


# --- A: cohort construction / membership -------------------------------


async def test_rejects_incompatible_target() -> None:
    repos = _Repos()
    repos.seed("claim-a", "M1", "outcome-a", "eval-a", Decimal("3.75"), Decimal("3.25"))
    repos.forecast.vintages["claim-b"] = [
        _numeric_forecast(
            "claim-b", "M2", Decimal("1.0"), _ts(10), target_key=_OTHER_NUMERIC_TARGET
        )
    ]
    repos.outcome.vintages["outcome-b"] = [
        _numeric_outcome("outcome-b", "M2", Decimal("1.0"), _ts(11))
    ]
    repos.evaluation.vintages["eval-b"] = [
        _numeric_evaluation("eval-b", "claim-b", "outcome-b", Decimal("0"), _ts(12))
    ]

    population = await repos.builder()(_cohort(), _ts(13))

    assert {m.evaluation.evaluation_key for m in population.accepted} == {"eval-a"}
    assert (
        "eval-b",
        ForecastPerformanceExclusionReason.INCOMPATIBLE_TARGET,
    ) in population.exclusions


async def test_rejects_incompatible_originator() -> None:
    repos = _Repos()
    repos.seed("claim-a", "M1", "outcome-a", "eval-a", Decimal("3.75"), Decimal("3.25"))
    other_attribution = _attribution(publisher_source_key="__fx66_other_publisher__")
    repos.forecast.vintages["claim-b"] = [
        _numeric_forecast("claim-b", "M2", Decimal("1.0"), _ts(10), attribution=other_attribution)
    ]
    repos.outcome.vintages["outcome-b"] = [
        _numeric_outcome("outcome-b", "M2", Decimal("1.0"), _ts(11))
    ]
    repos.evaluation.vintages["eval-b"] = [
        _numeric_evaluation("eval-b", "claim-b", "outcome-b", Decimal("0"), _ts(12))
    ]

    population = await repos.builder()(_cohort(), _ts(13))

    assert {m.evaluation.evaluation_key for m in population.accepted} == {"eval-a"}
    assert (
        "eval-b",
        ForecastPerformanceExclusionReason.INCOMPATIBLE_ORIGINATOR,
    ) in population.exclusions


async def test_named_institution_requires_matching_forecaster() -> None:
    repos = _Repos()
    cohort = _cohort(
        attribution_kind=ForecastAttributionKind.NAMED_INSTITUTION,
        originator_forecaster_source_key=_FORECASTER,
    )
    matching_attribution = _attribution(
        kind=ForecastAttributionKind.NAMED_INSTITUTION, forecaster_source_key=_FORECASTER
    )
    mismatched_attribution = _attribution(
        kind=ForecastAttributionKind.NAMED_INSTITUTION,
        forecaster_source_key="__fx66_other_forecaster__",
    )
    repos.forecast.vintages["claim-a"] = [
        _numeric_forecast(
            "claim-a", "M1", Decimal("3.75"), _ts(10), attribution=matching_attribution
        )
    ]
    repos.outcome.vintages["outcome-a"] = [
        _numeric_outcome("outcome-a", "M1", Decimal("3.25"), _ts(11))
    ]
    repos.evaluation.vintages["eval-a"] = [
        _numeric_evaluation("eval-a", "claim-a", "outcome-a", Decimal("-0.50"), _ts(12))
    ]
    repos.forecast.vintages["claim-b"] = [
        _numeric_forecast(
            "claim-b", "M2", Decimal("1.0"), _ts(10), attribution=mismatched_attribution
        )
    ]
    repos.outcome.vintages["outcome-b"] = [
        _numeric_outcome("outcome-b", "M2", Decimal("1.0"), _ts(11))
    ]
    repos.evaluation.vintages["eval-b"] = [
        _numeric_evaluation("eval-b", "claim-b", "outcome-b", Decimal("0"), _ts(12))
    ]

    population = await repos.builder()(cohort, _ts(13))

    assert {m.evaluation.evaluation_key for m in population.accepted} == {"eval-a"}


async def test_pit_excludes_not_yet_available_evaluation() -> None:
    repos = _Repos()
    repos.seed(
        "claim-a",
        "M1",
        "outcome-a",
        "eval-a",
        Decimal("3.75"),
        Decimal("3.25"),
        availability=_ts(20),
    )

    population = await repos.builder()(_cohort(), _ts(13))

    assert population.accepted == ()
    assert (
        "eval-a",
        ForecastPerformanceExclusionReason.NOT_YET_AVAILABLE,
    ) in population.exclusions


async def test_known_duplicate_evaluation_key_excluded() -> None:
    repos = _Repos()
    repos.seed("claim-a", "M1", "outcome-a", "eval-a", Decimal("3.75"), Decimal("3.25"))
    cohort = _cohort(known_duplicate_evaluation_keys=("eval-a",))

    population = await repos.builder()(cohort, _ts(13))

    assert population.accepted == ()
    assert (
        "eval-a",
        ForecastPerformanceExclusionReason.KNOWN_DUPLICATE_SYNDICATED,
    ) in population.exclusions


# --- B: duplicates and overlap ------------------------------------------


async def test_duplicate_forecast_issues_for_same_event_keep_earliest() -> None:
    repos = _Repos()
    repos.forecast.vintages["claim-early"] = [
        _numeric_forecast(
            "claim-early", "M1", Decimal("3.75"), _ts(10), original_publication_at=_ts(1)
        )
    ]
    repos.forecast.vintages["claim-late"] = [
        _numeric_forecast(
            "claim-late", "M1", Decimal("3.50"), _ts(10), original_publication_at=_ts(5)
        )
    ]
    repos.outcome.vintages["outcome-a"] = [
        _numeric_outcome("outcome-a", "M1", Decimal("3.25"), _ts(11))
    ]
    repos.evaluation.vintages["eval-early"] = [
        _numeric_evaluation("eval-early", "claim-early", "outcome-a", Decimal("-0.50"), _ts(12))
    ]
    repos.evaluation.vintages["eval-late"] = [
        _numeric_evaluation("eval-late", "claim-late", "outcome-a", Decimal("-0.25"), _ts(12))
    ]

    population = await repos.builder()(_cohort(), _ts(13))

    assert {m.evaluation.evaluation_key for m in population.accepted} == {"eval-early"}
    assert (
        "eval-late",
        ForecastPerformanceExclusionReason.SUPERSEDED_BY_EARLIER_QUALIFYING_ISSUE,
    ) in population.exclusions


async def test_unique_target_event_count_matches_distinct_outcomes() -> None:
    repos = _Repos()
    repos.seed("claim-a", "M1", "outcome-a", "eval-a", Decimal("3.75"), Decimal("3.25"))
    repos.seed("claim-b", "M2", "outcome-b", "eval-b", Decimal("3.50"), Decimal("3.50"))

    population = await repos.builder()(_cohort(), _ts(13))
    diagnostics = AssessForecastPerformanceEvidence()(population)

    assert diagnostics.accepted_count == 2
    assert diagnostics.unique_target_event_count == 2
    assert diagnostics.unique_forecast_issue_count == 2


# --- C: numeric metrics ---------------------------------------------------


async def test_numeric_metrics_are_correct() -> None:
    repos = _Repos()
    repos.seed(
        "claim-a", "M1", "outcome-a", "eval-a", Decimal("3.75"), Decimal("3.25")
    )  # error -0.50
    repos.seed(
        "claim-b", "M2", "outcome-b", "eval-b", Decimal("3.00"), Decimal("3.50")
    )  # error +0.50

    population = await repos.builder()(_cohort(), _ts(13))
    numeric_summary, categorical_summary, _ = CalculateForecastPerformance()(population)

    assert categorical_summary is None
    assert numeric_summary is not None
    assert numeric_summary.n == 2
    assert numeric_summary.unit == "PERCENT"
    assert numeric_summary.mean_absolute_error == Decimal("0.50")
    assert numeric_summary.mean_signed_error == Decimal("0.00")
    assert numeric_summary.root_mean_squared_error == Decimal("0.50")


async def test_numeric_metrics_zero_error_cohort() -> None:
    repos = _Repos()
    repos.seed("claim-a", "M1", "outcome-a", "eval-a", Decimal("3.25"), Decimal("3.25"))

    population = await repos.builder()(_cohort(), _ts(13))
    numeric_summary, _, _ = CalculateForecastPerformance()(population)

    assert numeric_summary is not None
    assert numeric_summary.mean_absolute_error == Decimal("0")
    assert numeric_summary.mean_signed_error == Decimal("0")
    assert numeric_summary.root_mean_squared_error == Decimal("0")


async def test_numeric_metrics_isolated_large_error() -> None:
    repos = _Repos()
    repos.seed("claim-a", "M1", "outcome-a", "eval-a", Decimal("3.25"), Decimal("3.25"))
    repos.seed("claim-b", "M2", "outcome-b", "eval-b", Decimal("0"), Decimal("10"))  # error +10

    population = await repos.builder()(_cohort(), _ts(13))
    numeric_summary, _, _ = CalculateForecastPerformance()(population)

    assert numeric_summary is not None
    assert numeric_summary.mean_absolute_error == Decimal("5")
    # RMSE weights the large error more heavily than MAE
    assert numeric_summary.root_mean_squared_error > numeric_summary.mean_absolute_error


async def test_empty_population_yields_no_numeric_summary() -> None:
    repos = _Repos()
    population = await repos.builder()(_cohort(), _ts(13))
    numeric_summary, categorical_summary, comparison = CalculateForecastPerformance()(population)

    assert numeric_summary is None
    assert categorical_summary is None
    assert comparison.status is ForecastPerformanceBenchmarkComparisonStatus.BENCHMARK_UNAVAILABLE


# --- D: categorical metrics ------------------------------------------------


def _seed_categorical(
    repos: _Repos,
    claim_key: str,
    meeting_id: str,
    outcome_key: str,
    evaluation_key: str,
    predicted: str,
    observed: str,
) -> None:
    repos.forecast.vintages[claim_key] = [
        _categorical_forecast(claim_key, meeting_id, predicted, _ts(10))
    ]
    repos.outcome.vintages[outcome_key] = [
        _categorical_outcome(outcome_key, meeting_id, observed, _ts(11))
    ]
    result = (
        CategoricalEvaluationResult.MATCH
        if predicted == observed
        else CategoricalEvaluationResult.MISMATCH
    )
    repos.evaluation.vintages[evaluation_key] = [
        _categorical_evaluation(evaluation_key, claim_key, outcome_key, result, _ts(12))
    ]


async def test_categorical_metrics_imbalanced_always_hold() -> None:
    repos = _Repos()
    cohort = _cohort(target_key=_CATEGORICAL_TARGET, forecast_type=ForecastType.CATEGORICAL_EVENT)
    pairs = [
        ("M1", "HOLD", "HOLD"),
        ("M2", "HOLD", "HOLD"),
        ("M3", "HOLD", "HOLD"),
        ("M4", "HOLD", "HOLD"),
        ("M5", "HOLD", "HOLD"),
        ("M6", "HOLD", "HOLD"),
        ("M7", "HOLD", "HOLD"),
        ("M8", "HOLD", "HOLD"),
        ("M9", "HOLD", "HOLD"),
        ("M10", "HOLD", "CUT"),
    ]
    for i, (meeting_id, predicted, observed) in enumerate(pairs):
        _seed_categorical(
            repos, f"claim-{i}", meeting_id, f"outcome-{i}", f"eval-{i}", predicted, observed
        )

    population = await repos.builder()(cohort, _ts(13))
    _, categorical_summary, _ = CalculateForecastPerformance()(population)

    assert categorical_summary is not None
    assert categorical_summary.n == 10
    assert categorical_summary.match_count == 9
    assert categorical_summary.accuracy == Decimal("0.9")
    assert ("HOLD", "CUT", 1) in categorical_summary.confusion_counts
    assert ("HOLD", "HOLD", 9) in categorical_summary.confusion_counts
    # class imbalance: realized outcomes are almost all HOLD too
    realized = dict(categorical_summary.realized_class_distribution)
    assert realized["HOLD"] == 9
    assert realized["CUT"] == 1


# --- E: benchmarks -----------------------------------------------------


async def test_naive_numeric_benchmark_comparison() -> None:
    repos = _Repos()
    repos.seed(
        "claim-a", "M1", "outcome-a", "eval-a", Decimal("3.75"), Decimal("3.25")
    )  # abs error 0.50

    population = await repos.builder()(_cohort(), _ts(13))
    benchmark = ForecastPerformanceBenchmarkDefinition(
        benchmark_key="naive-numeric",
        version_sequence=0,
        kind=ForecastPerformanceBenchmarkKind.NAIVE_NUMERIC,
        target_key=_NUMERIC_TARGET,
        horizon_category="SAME-MEETING",
        metric=ForecastEvaluationMetric.NUMERIC_ERROR,
        availability=_ts(9),
        rationale="naive no-change benchmark",
        naive_numeric_reference_value=Decimal("4.00"),  # abs error 0.75 against the real outcome
        naive_numeric_reference_description="fixed reference value",
    )
    _, _, comparison = CalculateForecastPerformance()(population, benchmark=benchmark)

    assert comparison.status is ForecastPerformanceBenchmarkComparisonStatus.COMPARED
    assert comparison.paired_count == 1
    assert comparison.source_mean_absolute_error == Decimal("0.50")
    assert comparison.benchmark_mean_absolute_error == Decimal("0.75")
    assert comparison.relative_mae_improvement == Decimal(1) - (Decimal("0.50") / Decimal("0.75"))


async def test_naive_categorical_benchmark_comparison() -> None:
    repos = _Repos()
    cohort = _cohort(target_key=_CATEGORICAL_TARGET, forecast_type=ForecastType.CATEGORICAL_EVENT)
    _seed_categorical(repos, "claim-a", "M1", "outcome-a", "eval-a", "HOLD", "HOLD")
    _seed_categorical(repos, "claim-b", "M2", "outcome-b", "eval-b", "CUT", "CUT")

    population = await repos.builder()(cohort, _ts(13))
    benchmark = ForecastPerformanceBenchmarkDefinition(
        benchmark_key="naive-hold",
        version_sequence=0,
        kind=ForecastPerformanceBenchmarkKind.NAIVE_CATEGORICAL,
        target_key=_CATEGORICAL_TARGET,
        horizon_category="SAME-MEETING",
        metric=ForecastEvaluationMetric.CATEGORICAL_MATCH,
        availability=_ts(9),
        rationale="always predict HOLD",
        naive_categorical_class="HOLD",
    )
    _, _, comparison = CalculateForecastPerformance()(population, benchmark=benchmark)

    assert comparison.status is ForecastPerformanceBenchmarkComparisonStatus.COMPARED
    assert comparison.source_accuracy == Decimal("1")
    assert comparison.benchmark_accuracy == Decimal("0.5")  # naive HOLD matches only M1


async def test_authenticated_series_benchmark_pairs_by_shared_outcome_key() -> None:
    repos = _Repos()
    repos.seed(
        "claim-a", "M1", "outcome-a", "eval-a", Decimal("3.75"), Decimal("3.25")
    )  # abs error 0.50
    population = await repos.builder()(_cohort(), _ts(13))

    bench_repos = _Repos()
    bench_cohort = _cohort(
        cohort_key="__fx66_bench_cohort__",
        originator_publisher_source_key="__fx66_bench_publisher__",
    )
    bench_repos.forecast.vintages["bench-claim-a"] = [
        _numeric_forecast(
            "bench-claim-a",
            "M1",
            Decimal("3.00"),
            _ts(10),
            attribution=_attribution(publisher_source_key="__fx66_bench_publisher__"),
        )
    ]
    bench_repos.outcome.vintages["outcome-a"] = [
        _numeric_outcome("outcome-a", "M1", Decimal("3.25"), _ts(11))
    ]
    bench_repos.evaluation.vintages["bench-eval-a"] = [
        _numeric_evaluation("bench-eval-a", "bench-claim-a", "outcome-a", Decimal("0.25"), _ts(12))
    ]
    benchmark_population = await bench_repos.builder()(bench_cohort, _ts(13))

    benchmark = ForecastPerformanceBenchmarkDefinition(
        benchmark_key="other-cohort-benchmark",
        version_sequence=0,
        kind=ForecastPerformanceBenchmarkKind.AUTHENTICATED_SERIES,
        target_key=_NUMERIC_TARGET,
        horizon_category="SAME-MEETING",
        metric=ForecastEvaluationMetric.NUMERIC_ERROR,
        availability=_ts(9),
        rationale="compare against another real cohort",
        benchmark_cohort_key=bench_cohort.cohort_key,
        benchmark_cohort_version_sequence=bench_cohort.version_sequence,
    )
    _, _, comparison = CalculateForecastPerformance()(
        population, benchmark=benchmark, benchmark_population=benchmark_population
    )

    assert comparison.status is ForecastPerformanceBenchmarkComparisonStatus.COMPARED
    assert comparison.paired_count == 1
    assert comparison.source_mean_absolute_error == Decimal("0.50")
    assert comparison.benchmark_mean_absolute_error == Decimal("0.25")


async def test_missing_benchmark_is_reported_not_fabricated() -> None:
    repos = _Repos()
    repos.seed("claim-a", "M1", "outcome-a", "eval-a", Decimal("3.75"), Decimal("3.25"))
    population = await repos.builder()(_cohort(), _ts(13))

    _, _, comparison = CalculateForecastPerformance()(population, benchmark=None)

    assert comparison.status is ForecastPerformanceBenchmarkComparisonStatus.BENCHMARK_UNAVAILABLE
    assert comparison.paired_count == 0


async def test_authenticated_series_with_no_paired_events_is_unavailable() -> None:
    repos = _Repos()
    repos.seed("claim-a", "M1", "outcome-a", "eval-a", Decimal("3.75"), Decimal("3.25"))
    population = await repos.builder()(_cohort(), _ts(13))

    bench_repos = _Repos()
    bench_repos.seed(
        "bench-claim-b", "M2", "outcome-b", "bench-eval-b", Decimal("1.0"), Decimal("1.0")
    )
    bench_cohort = _cohort(cohort_key="__fx66_bench_cohort_2__")
    benchmark_population = await bench_repos.builder()(bench_cohort, _ts(13))

    benchmark = ForecastPerformanceBenchmarkDefinition(
        benchmark_key="other-cohort-benchmark-2",
        version_sequence=0,
        kind=ForecastPerformanceBenchmarkKind.AUTHENTICATED_SERIES,
        target_key=_NUMERIC_TARGET,
        horizon_category="SAME-MEETING",
        metric=ForecastEvaluationMetric.NUMERIC_ERROR,
        availability=_ts(9),
        rationale="no overlap",
        benchmark_cohort_key=bench_cohort.cohort_key,
        benchmark_cohort_version_sequence=bench_cohort.version_sequence,
    )
    _, _, comparison = CalculateForecastPerformance()(
        population, benchmark=benchmark, benchmark_population=benchmark_population
    )

    assert comparison.status is ForecastPerformanceBenchmarkComparisonStatus.BENCHMARK_UNAVAILABLE


# --- F: evidence sufficiency ---------------------------------------------


async def test_small_sample_is_insufficient_data() -> None:
    repos = _Repos()
    repos.seed("claim-a", "M1", "outcome-a", "eval-a", Decimal("3.75"), Decimal("3.25"))

    population = await repos.builder()(_cohort(), _ts(13))
    diagnostics = AssessForecastPerformanceEvidence()(population)

    assert diagnostics.sample_adequacy is ForecastPerformanceSampleAdequacy.INSUFFICIENT_DATA


async def test_research_mode_never_exceeds_descriptive_only_regardless_of_size() -> None:
    repos = _Repos()
    for i in range(40):
        repos.seed(
            f"claim-{i}", f"M{i}", f"outcome-{i}", f"eval-{i}", Decimal("3.75"), Decimal("3.25")
        )

    population = await repos.builder()(
        _cohort(evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH), _ts(13)
    )
    diagnostics = AssessForecastPerformanceEvidence()(population)

    assert diagnostics.accepted_count == 40
    assert diagnostics.sample_adequacy is ForecastPerformanceSampleAdequacy.DESCRIPTIVE_ONLY


async def test_production_mode_large_sample_supports_inference() -> None:
    repos = _Repos()
    for i in range(40):
        repos.seed(
            f"claim-{i}",
            f"M{i}",
            f"outcome-{i}",
            f"eval-{i}",
            Decimal("3.75"),
            Decimal("3.25"),
            mode=ForecastProvenanceMode.PRODUCTION_OBSERVED,
        )

    population = await repos.builder()(
        _cohort(evaluation_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED), _ts(13)
    )
    diagnostics = AssessForecastPerformanceEvidence()(population)

    assert diagnostics.accepted_count == 40
    assert diagnostics.sample_adequacy is ForecastPerformanceSampleAdequacy.INFERENCE_SUPPORTED


async def test_exclusion_counts_are_reported_in_diagnostics() -> None:
    repos = _Repos()
    repos.seed("claim-a", "M1", "outcome-a", "eval-a", Decimal("3.75"), Decimal("3.25"))
    cohort = _cohort(known_duplicate_evaluation_keys=("eval-a",))

    population = await repos.builder()(cohort, _ts(13))
    diagnostics = AssessForecastPerformanceEvidence()(population)

    assert diagnostics.accepted_count == 0
    assert diagnostics.raw_candidate_count == 1
    assert (ForecastPerformanceExclusionReason.KNOWN_DUPLICATE_SYNDICATED, 1) in (
        diagnostics.excluded_by_reason
    )
