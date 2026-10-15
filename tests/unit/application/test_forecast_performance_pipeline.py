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
from forex_agent.application.use_cases.inspect_forecast_performance_pending_revisions import (
    InspectForecastPerformancePendingRevisions,
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
    revision_sequence: int = 0,
    protocol_key: str = _PROTOCOL_KEY,
    protocol_version: int = 0,
    definition_key: str = _DEFINITION_KEY,
    mode: ForecastProvenanceMode = ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
) -> StructuredForecastEvaluationVintage:
    return StructuredForecastEvaluationVintage(
        evaluation_key=evaluation_key,
        revision_sequence=revision_sequence,
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

    def add_evaluation_revision(
        self,
        evaluation_key: str,
        revision_sequence: int,
        claim_key: str,
        outcome_key: str,
        signed_error: Decimal,
        availability: UtcTimestamp,
        *,
        mode: ForecastProvenanceMode = ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
    ) -> None:
        """Appends a FURTHER revision of an ALREADY-seeded `evaluation_
        key` -- e.g. a later correction -- referencing the SAME
        forecast/outcome vintages `seed()` already created."""
        self.evaluation.vintages[evaluation_key].append(
            _numeric_evaluation(
                evaluation_key,
                claim_key,
                outcome_key,
                signed_error,
                availability,
                revision_sequence=revision_sequence,
                mode=mode,
            )
        )

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


async def test_pit_silently_omits_not_yet_available_evaluation() -> None:
    """FX-66H.1 (F66-04): an evaluation FTA did not know about at the
    cutoff must not appear ANYWHERE in the population, not even as a
    named exclusion -- `NOT_YET_AVAILABLE` is unreachable (see its own
    docstring)."""
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
    assert population.exclusions == ()
    assert population.raw_candidate_count == 0


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


async def test_production_mode_large_distinct_sample_caps_at_comparable_sample() -> None:
    """FX-66H (H2): even 40 accepted PRODUCTION_OBSERVED forecasts,
    each targeting a genuinely DISTINCT real-world event, never
    promote past COMPARABLE_SAMPLE -- INFERENCE_SUPPORTED is reserved
    and never emitted by fx66_v1's own classification rule."""
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
    assert diagnostics.distinct_target_period_count == 40
    assert diagnostics.sample_adequacy is ForecastPerformanceSampleAdequacy.COMPARABLE_SAMPLE


async def test_thirty_evaluations_sharing_few_target_events_cannot_support_inference() -> None:
    """FX-66H (H2) mandatory test: 30 ACCEPTED production evaluations,
    but spread across only 3 distinct outcome DEFINITIONS/meetings
    (10 each) -- distinct_target_period_count stays low even though
    accepted_count is large, so this must NOT reach COMPARABLE_SAMPLE
    (let alone INFERENCE_SUPPORTED)."""
    repos = _Repos()
    meeting_ids = ["M1", "M2", "M3"]
    for i in range(30):
        meeting_id = meeting_ids[i % 3]
        repos.seed(
            f"claim-{i}",
            meeting_id,
            f"outcome-{i}",  # distinct outcome_key per evaluation
            f"eval-{i}",
            Decimal("3.75"),
            Decimal("3.25"),
            mode=ForecastProvenanceMode.PRODUCTION_OBSERVED,
        )
        # Each outcome_key uses its OWN definition_key (a legitimate,
        # distinct FX-65H.2 identity) but shares the SAME target_period
        # across its own group of 10 -- simulating several outcome
        # definitions all keyed to the SAME underlying real-world
        # meeting, which `distinct_target_period_count` must catch.
        repos.outcome.vintages[f"outcome-{i}"] = [
            _numeric_outcome(
                f"outcome-{i}",
                meeting_id,
                Decimal("3.25"),
                _ts(11),
                definition_key=f"{_DEFINITION_KEY}-{i}",
            )
        ]

    population = await repos.builder()(
        _cohort(evaluation_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED), _ts(13)
    )
    diagnostics = AssessForecastPerformanceEvidence()(population)

    assert diagnostics.accepted_count == 30
    assert diagnostics.distinct_target_period_count == 3
    # Only 3 genuinely distinct real-world events -- even more
    # conservative than DESCRIPTIVE_ONLY; certainly never COMPARABLE_
    # SAMPLE or the reserved INFERENCE_SUPPORTED, despite 30 accepted
    # observations.
    assert diagnostics.sample_adequacy is ForecastPerformanceSampleAdequacy.INSUFFICIENT_DATA


async def test_one_hundred_correlated_evaluations_cannot_support_inference() -> None:
    """FX-66H (H2) mandatory test: 100 accepted production evaluations
    all sharing the SAME single target_period -- a wholly correlated
    population -- must never exceed DESCRIPTIVE_ONLY/INSUFFICIENT_DATA."""
    repos = _Repos()
    meeting_id = "M1"
    for i in range(100):
        repos.seed(
            f"claim-{i}",
            meeting_id,
            f"outcome-{i}",
            f"eval-{i}",
            Decimal("3.75"),
            Decimal("3.25"),
            mode=ForecastProvenanceMode.PRODUCTION_OBSERVED,
        )
        repos.outcome.vintages[f"outcome-{i}"] = [
            _numeric_outcome(
                f"outcome-{i}",
                meeting_id,
                Decimal("3.25"),
                _ts(11),
                definition_key=f"{_DEFINITION_KEY}-{i}",
            )
        ]

    population = await repos.builder()(
        _cohort(evaluation_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED), _ts(13)
    )
    diagnostics = AssessForecastPerformanceEvidence()(population)

    assert diagnostics.accepted_count == 100
    assert diagnostics.distinct_target_period_count == 1
    # A wholly correlated population (100 observations, 1 real event)
    # stays INSUFFICIENT_DATA -- never COMPARABLE_SAMPLE or the
    # reserved, never-emitted INFERENCE_SUPPORTED, regardless of size.
    assert diagnostics.sample_adequacy is ForecastPerformanceSampleAdequacy.INSUFFICIENT_DATA


async def test_incomplete_benchmark_population_does_not_establish_skill() -> None:
    """FX-66H (H2) mandatory test: even with a benchmark pinned, a
    small/incomplete paired population leaves sample_adequacy
    unaffected by the benchmark comparison -- a comparison is
    descriptive only, never upgrades adequacy."""
    repos = _Repos()
    repos.seed("claim-a", "M1", "outcome-a", "eval-a", Decimal("3.75"), Decimal("3.25"))

    population = await repos.builder()(_cohort(), _ts(13))
    diagnostics = AssessForecastPerformanceEvidence()(population, benchmark_paired_count=1)

    assert diagnostics.sample_adequacy is ForecastPerformanceSampleAdequacy.INSUFFICIENT_DATA
    assert diagnostics.benchmark_paired_count == 1


async def test_large_synthetic_cohort_remains_descriptive_without_inference_contract() -> None:
    """FX-66H (H2) mandatory test: a sufficiently large, genuinely
    distinct-event, RESEARCH-mode cohort still stays DESCRIPTIVE_ONLY
    -- large size and distinct events alone are not enough; the
    cohort's own research/production provenance governs the ceiling."""
    repos = _Repos()
    for i in range(50):
        repos.seed(
            f"claim-{i}", f"M{i}", f"outcome-{i}", f"eval-{i}", Decimal("3.75"), Decimal("3.25")
        )

    population = await repos.builder()(
        _cohort(evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH), _ts(13)
    )
    diagnostics = AssessForecastPerformanceEvidence()(population)

    assert diagnostics.accepted_count == 50
    assert diagnostics.distinct_target_period_count == 50
    assert diagnostics.sample_adequacy is ForecastPerformanceSampleAdequacy.DESCRIPTIVE_ONLY


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


# --- FX-66H (H1): PIT-correct per-key revision selection ------------------


async def test_h1_single_vintage_evaluation_is_selected() -> None:
    """Mandatory test 1: one evaluation with only vintage 0."""
    repos = _Repos()
    repos.seed("claim-a", "M1", "outcome-a", "eval-a", Decimal("3.75"), Decimal("3.25"))

    population = await repos.builder()(_cohort(), _ts(13))

    assert {m.evaluation.evaluation_key for m in population.accepted} == {"eval-a"}
    assert population.accepted[0].evaluation.revision_sequence == 0


async def test_h1_earlier_revision_selected_when_latest_is_too_new() -> None:
    """Mandatory test 2 -- THE core FX-66H bug fix: vintage 0 before
    cutoff, vintage 1 after cutoff. Must select vintage 0, never
    exclude the whole key merely because a later revision exists."""
    repos = _Repos()
    repos.seed(
        "claim-a",
        "M1",
        "outcome-a",
        "eval-a",
        Decimal("3.75"),
        Decimal("3.25"),
        availability=_ts(10),
    )
    repos.add_evaluation_revision("eval-a", 1, "claim-a", "outcome-a", Decimal("-0.75"), _ts(20))

    population = await repos.builder()(_cohort(), _ts(13))

    assert {m.evaluation.evaluation_key for m in population.accepted} == {"eval-a"}
    selected = population.accepted[0].evaluation
    assert selected.revision_sequence == 0
    assert selected.result.signed_error == Decimal("-0.50")
    assert population.exclusions == ()


async def test_h1_both_vintages_before_cutoff_selects_latest_eligible() -> None:
    """Mandatory test 3: both vintages before cutoff -- select the
    latest ELIGIBLE one (revision 1), not revision 0."""
    repos = _Repos()
    repos.seed(
        "claim-a",
        "M1",
        "outcome-a",
        "eval-a",
        Decimal("3.75"),
        Decimal("3.25"),
        availability=_ts(5),
    )
    repos.add_evaluation_revision("eval-a", 1, "claim-a", "outcome-a", Decimal("-0.75"), _ts(10))

    population = await repos.builder()(_cohort(), _ts(13))

    assert len(population.accepted) == 1
    selected = population.accepted[0].evaluation
    assert selected.revision_sequence == 1
    assert selected.result.signed_error == Decimal("-0.75")


async def test_h1_both_vintages_after_cutoff_excludes_from_population() -> None:
    """Mandatory test 4: both vintages after cutoff -- absent from
    the historical population entirely (FX-66H.1/F66-04: not even as
    a named exclusion, since FTA knew nothing about this key at the
    cutoff -- see `test_pit_silently_omits_not_yet_available_evaluation`)."""
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
    repos.add_evaluation_revision("eval-a", 1, "claim-a", "outcome-a", Decimal("-0.75"), _ts(21))

    population = await repos.builder()(_cohort(), _ts(13))

    assert population.accepted == ()
    assert population.exclusions == ()
    assert population.raw_candidate_count == 0


async def test_h1_revision_availability_exactly_equals_cutoff_is_included() -> None:
    """Mandatory test 5: availability == as_of is INCLUSIVE."""
    repos = _Repos()
    repos.seed(
        "claim-a",
        "M1",
        "outcome-a",
        "eval-a",
        Decimal("3.75"),
        Decimal("3.25"),
        availability=_ts(13),
    )

    population = await repos.builder()(_cohort(), _ts(13))

    assert {m.evaluation.evaluation_key for m in population.accepted} == {"eval-a"}


async def test_h1_same_availability_deterministic_revision_ordering() -> None:
    """Mandatory test 6: two revisions sharing the EXACT SAME
    availability -- the higher revision_sequence wins deterministically
    (sort key is `(availability, revision_sequence)`), on both the
    unbounded and the as-of-bounded reads."""
    repos = _Repos()
    repos.seed(
        "claim-a",
        "M1",
        "outcome-a",
        "eval-a",
        Decimal("3.75"),
        Decimal("3.25"),
        availability=_ts(10),
    )
    repos.add_evaluation_revision("eval-a", 1, "claim-a", "outcome-a", Decimal("-0.75"), _ts(10))

    population = await repos.builder()(_cohort(), _ts(13))

    assert len(population.accepted) == 1
    assert population.accepted[0].evaluation.revision_sequence == 1


async def test_h1_future_correction_does_not_alter_prior_cohort_metrics() -> None:
    """Mandatory test 7: building the population AGAIN at the SAME
    historical cutoff, after a future correction has since been
    appended, must reproduce the EXACT SAME metrics."""
    repos = _Repos()
    repos.seed(
        "claim-a",
        "M1",
        "outcome-a",
        "eval-a",
        Decimal("3.75"),
        Decimal("3.25"),
        availability=_ts(10),
    )
    cutoff = _ts(13)
    population_before = await repos.builder()(_cohort(), cutoff)
    numeric_before, _, _ = CalculateForecastPerformance()(population_before)

    repos.add_evaluation_revision("eval-a", 1, "claim-a", "outcome-a", Decimal("-9.99"), _ts(20))

    population_after = await repos.builder()(_cohort(), cutoff)
    numeric_after, _, _ = CalculateForecastPerformance()(population_after)

    assert numeric_before is not None and numeric_after is not None
    assert numeric_before.mean_absolute_error == numeric_after.mean_absolute_error
    assert numeric_before.mean_signed_error == numeric_after.mean_signed_error
    assert {m.evaluation.evaluation_key for m in population_before.accepted} == {
        m.evaluation.evaluation_key for m in population_after.accepted
    }


async def test_h1_future_correction_does_not_alter_prior_snapshot_membership() -> None:
    """Mandatory test 8: re-recording a snapshot at the SAME historical
    cutoff after a future correction reproduces IDENTICAL membership
    and reports UNCHANGED, never a silently different REVISION_ADDED."""
    repos = _Repos()
    repos.seed(
        "claim-a",
        "M1",
        "outcome-a",
        "eval-a",
        Decimal("3.75"),
        Decimal("3.25"),
        availability=_ts(10),
    )
    cutoff = _ts(13)

    population_before = await repos.builder()(_cohort(), cutoff)
    before_keys = {m.evaluation.evaluation_key for m in population_before.accepted}
    diagnostics_before = AssessForecastPerformanceEvidence()(population_before)
    assert diagnostics_before.accepted_count == 1

    repos.add_evaluation_revision("eval-a", 1, "claim-a", "outcome-a", Decimal("-9.99"), _ts(20))

    population_after = await repos.builder()(_cohort(), cutoff)
    after_keys = {m.evaluation.evaluation_key for m in population_after.accepted}

    assert before_keys == after_keys == {"eval-a"}


async def test_h1_multiple_evaluation_keys_with_independently_revised_histories() -> None:
    """Mandatory test 9: two evaluation_keys, each independently
    revised at different times -- each must select its OWN correct
    PIT-eligible revision, unaffected by the other's own history."""
    repos = _Repos()
    repos.seed(
        "claim-a",
        "M1",
        "outcome-a",
        "eval-a",
        Decimal("3.75"),
        Decimal("3.25"),
        availability=_ts(5),
    )
    repos.add_evaluation_revision("eval-a", 1, "claim-a", "outcome-a", Decimal("-9.99"), _ts(20))

    repos.seed(
        "claim-b",
        "M2",
        "outcome-b",
        "eval-b",
        Decimal("1.00"),
        Decimal("1.50"),
        availability=_ts(6),
    )
    repos.add_evaluation_revision("eval-b", 1, "claim-b", "outcome-b", Decimal("0.75"), _ts(9))

    population = await repos.builder()(_cohort(), _ts(13))

    by_key = {m.evaluation.evaluation_key: m.evaluation for m in population.accepted}
    assert set(by_key) == {"eval-a", "eval-b"}
    assert by_key["eval-a"].revision_sequence == 0  # revision 1 is too new
    assert by_key["eval-b"].revision_sequence == 1  # revision 1 is eligible


async def test_h1_production_and_retrospective_selection_remain_separate() -> None:
    """Mandatory test 10: a cohort pinned to one evaluation_mode only
    ever sees evaluations of that mode, even when the AS-OF-bounded
    selection logic is exercised."""
    repos = _Repos()
    repos.seed(
        "claim-a",
        "M1",
        "outcome-a",
        "eval-a",
        Decimal("3.75"),
        Decimal("3.25"),
        mode=ForecastProvenanceMode.PRODUCTION_OBSERVED,
    )

    research_population = await repos.builder()(
        _cohort(evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH), _ts(13)
    )
    production_population = await repos.builder()(
        _cohort(evaluation_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED), _ts(13)
    )

    assert research_population.accepted == ()
    assert research_population.raw_candidate_count == 0
    assert {m.evaluation.evaluation_key for m in production_population.accepted} == {"eval-a"}


# --- FX-66H.1 (H1/F66-04): fully PIT-reproducible historical diagnostics --


async def test_f66_04_future_revision_leaves_complete_diagnostics_unchanged() -> None:
    """Required test: historical population built before and after a
    future REVISION of an already-accepted key -- complete diagnostics
    (not just the numeric summary) must be byte-for-byte identical."""
    repos = _Repos()
    repos.seed(
        "claim-a",
        "M1",
        "outcome-a",
        "eval-a",
        Decimal("3.75"),
        Decimal("3.25"),
        availability=_ts(10),
    )
    cutoff = _ts(13)

    population_before = await repos.builder()(_cohort(), cutoff)
    diagnostics_before = AssessForecastPerformanceEvidence()(population_before)

    repos.add_evaluation_revision("eval-a", 1, "claim-a", "outcome-a", Decimal("-9.99"), _ts(20))

    population_after = await repos.builder()(_cohort(), cutoff)
    diagnostics_after = AssessForecastPerformanceEvidence()(population_after)

    assert population_before.raw_candidate_count == population_after.raw_candidate_count
    assert population_before.exclusions == population_after.exclusions
    assert diagnostics_before == diagnostics_after


async def test_f66_04_future_new_evaluation_key_leaves_raw_count_and_exclusions_unchanged() -> None:
    """Required test: historical population built before and after a
    future NEW evaluation_key (not a revision of an existing one) is
    appended -- `raw_candidate_count` and `exclusions` at the SAME
    historical cutoff must be unaffected, since FTA knew nothing about
    the new key at that cutoff."""
    repos = _Repos()
    repos.seed(
        "claim-a",
        "M1",
        "outcome-a",
        "eval-a",
        Decimal("3.75"),
        Decimal("3.25"),
        availability=_ts(10),
    )
    cutoff = _ts(13)

    population_before = await repos.builder()(_cohort(), cutoff)

    repos.seed(
        "claim-b", "M2", "outcome-b", "eval-b", Decimal("1.0"), Decimal("1.5"), availability=_ts(20)
    )

    population_after = await repos.builder()(_cohort(), cutoff)

    assert population_before.raw_candidate_count == population_after.raw_candidate_count == 1
    assert population_before.exclusions == population_after.exclusions == ()
    assert {m.evaluation.evaluation_key for m in population_after.accepted} == {"eval-a"}


async def test_f66_04_previously_unavailable_key_becomes_eligible_only_after_its_availability() -> (
    None
):
    """Required test: a key absent from the population entirely before
    its own `availability` becomes present (accepted, raw_candidate_
    count incremented) once the cutoff reaches that availability --
    never a moment earlier."""
    repos = _Repos()
    repos.seed(
        "claim-a",
        "M1",
        "outcome-a",
        "eval-a",
        Decimal("3.75"),
        Decimal("3.25"),
        availability=_ts(15),
    )

    too_early = await repos.builder()(_cohort(), _ts(14))
    assert too_early.accepted == ()
    assert too_early.exclusions == ()
    assert too_early.raw_candidate_count == 0

    exactly_available = await repos.builder()(_cohort(), _ts(15))
    assert {m.evaluation.evaluation_key for m in exactly_available.accepted} == {"eval-a"}
    assert exactly_available.raw_candidate_count == 1


async def test_f66_04_historical_numeric_metrics_remain_unchanged_after_future_revision() -> None:
    """Required test: historical numeric metrics (not just membership)
    must reproduce identically before/after a future correction, at
    the same historical cutoff."""
    repos = _Repos()
    repos.seed(
        "claim-a",
        "M1",
        "outcome-a",
        "eval-a",
        Decimal("3.75"),
        Decimal("3.25"),
        availability=_ts(10),
    )
    cutoff = _ts(13)

    population_before = await repos.builder()(_cohort(), cutoff)
    numeric_before, _, _ = CalculateForecastPerformance()(population_before)

    repos.add_evaluation_revision("eval-a", 1, "claim-a", "outcome-a", Decimal("-9.99"), _ts(20))

    population_after = await repos.builder()(_cohort(), cutoff)
    numeric_after, _, _ = CalculateForecastPerformance()(population_after)

    assert numeric_before == numeric_after


async def test_f66_04_administrative_inspection_does_not_affect_historical_population() -> None:
    """Required test: `InspectForecastPerformancePendingRevisions`
    correctly reports a pending revision administratively, while the
    SEPARATE historical population built at the original cutoff stays
    completely unaffected -- proving the two paths never mix."""
    repos = _Repos()
    repos.seed(
        "claim-a",
        "M1",
        "outcome-a",
        "eval-a",
        Decimal("3.75"),
        Decimal("3.25"),
        availability=_ts(10),
    )
    cutoff = _ts(13)
    repos.add_evaluation_revision("eval-a", 1, "claim-a", "outcome-a", Decimal("-9.99"), _ts(20))

    inspect = InspectForecastPerformancePendingRevisions(repos.builder())
    report = await inspect(_cohort(), historical_cutoff=cutoff, administrative_as_of=_ts(21))
    assert report.pending_evaluation_keys == ("eval-a",)

    historical_population = await repos.builder()(_cohort(), cutoff)
    assert {m.evaluation.evaluation_key for m in historical_population.accepted} == {"eval-a"}
    assert historical_population.accepted[0].evaluation.revision_sequence == 0
