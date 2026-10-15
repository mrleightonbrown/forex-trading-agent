"""FX-66 Section 19 (Dataset A -- real curated evidence): runs the
full performance pipeline against the ONE real, authenticated FX-65
evaluation this codebase currently holds (the Bank of Canada Market
Participants Survey Q3 2024 forecast, evaluated against the real
2024-12-11 Fixed Announcement Date decision -- see `scripts/import_
pilot_forecast_evaluation.py`).

**This demonstrates correct mechanics on real data, NOT forecasting
skill.** With exactly one real evaluation, `AssessForecastPerformance
Evidence` MUST, and does, report `INSUFFICIENT_DATA` -- the existing
real corpus is explicitly NOT sufficient to demonstrate historical
forecasting skill (Section 19's own opening sentence). No additional
real forecasts are fabricated to make the population appear
statistically useful.

Run:
    uv run python scripts/demonstrate_forecast_performance_pilot.py
    uv run python scripts/demonstrate_forecast_performance_pilot.py --dry-run

Requires:
    - `docker compose up -d db` (and `alembic upgrade head` already applied)
    - FX-65's own `scripts/import_pilot_forecast_evaluation.py` already run
      (reuses its real evaluation_key verbatim)
"""

import argparse
import asyncio
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import async_sessionmaker

from forex_agent.application.use_cases.assess_forecast_performance_evidence import (
    AssessForecastPerformanceEvidence,
)
from forex_agent.application.use_cases.build_forecast_performance_population_as_of import (
    BuildForecastPerformancePopulationAsOf,
)
from forex_agent.application.use_cases.calculate_forecast_performance import (
    CalculateForecastPerformance,
)
from forex_agent.application.use_cases.define_forecast_performance_cohort import (
    DefineForecastPerformanceCohort,
)
from forex_agent.application.use_cases.define_forecast_performance_methodology import (
    DefineForecastPerformanceMethodology,
)
from forex_agent.application.use_cases.get_forecast_performance_snapshot_as_of import (
    GetForecastPerformanceSnapshotAsOf,
)
from forex_agent.application.use_cases.get_retrospective_forecast_performance_research_view import (
    GetRetrospectiveForecastPerformanceResearchView,
)
from forex_agent.application.use_cases.record_forecast_performance_snapshot import (
    RecordForecastPerformanceSnapshot,
)
from forex_agent.domain.forecast_attribution_kind import ForecastAttributionKind
from forex_agent.domain.forecast_performance_cohort_definition import (
    ForecastPerformanceCohortDefinition,
)
from forex_agent.domain.forecast_performance_duplicate_selection_policy import (
    ForecastPerformanceDuplicateSelectionPolicy,
)
from forex_agent.domain.forecast_performance_methodology import ForecastPerformanceMethodology
from forex_agent.domain.forecast_performance_missing_data_policy import (
    ForecastPerformanceMissingDataPolicy,
)
from forex_agent.domain.forecast_performance_sample_adequacy import (
    ForecastPerformanceSampleAdequacy,
)
from forex_agent.domain.forecast_performance_snapshot import (
    ForecastPerformanceSnapshot,
    ForecastPerformanceSnapshotMember,
)
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.forecast_evaluation_repository import (
    SqlAlchemyForecastEvaluationRepository,
)
from forex_agent.infrastructure.db.forecast_outcome_repository import (
    SqlAlchemyForecastOutcomeRepository,
)
from forex_agent.infrastructure.db.forecast_performance_repository import (
    SqlAlchemyForecastPerformanceRepository,
)
from forex_agent.infrastructure.db.session import get_engine
from forex_agent.infrastructure.db.structured_forecast_repository import (
    SqlAlchemyStructuredForecastRepository,
)

_PUBLISHER_SOURCE_KEY = "BANK_OF_CANADA"
_TARGET_KEY = "CA_POLICY_RATE_LEVEL_AFTER_MEETING"
_PROTOCOL_KEY = "boc-rate-fad-protocol"
_COHORT_KEY = "BOC-MPS-FAD-SAME-MEETING-COHORT"
_METHODOLOGY_KEY = f"{_COHORT_KEY}-methodology"
_SNAPSHOT_KEY = f"PERF:{_COHORT_KEY}:{_METHODOLOGY_KEY}"

# This human registration happened ONCE -- fixed, never `now()`, so a
# repeat run of this script does not manufacture new registration
# events merely because the script happens to run again later.
_REGISTERED_AT = UtcTimestamp(datetime(2026, 10, 15, tzinfo=UTC))

# The PIT bound this demonstration asks "what did we know as of this
# instant" against -- ALSO fixed, for the SAME reason: `knowledge_
# cutoff` is part of `RecordForecastPerformanceSnapshot`'s own
# determinism BASIS (by design, mirroring `EvaluateStructuredForecast`'s
# own basis), so a fresh `now()` here would mint a genuinely NEW basis
# on every re-run, defeating idempotency -- exactly the "any value
# meant to represent a stable point must be fixed, never recomputed
# via now()" lesson this epic has already learned twice (FX-65/FX-65H).
_KNOWLEDGE_CUTOFF = _REGISTERED_AT


def _now() -> UtcTimestamp:
    return UtcTimestamp(datetime.now(UTC))


def _cohort() -> ForecastPerformanceCohortDefinition:
    return ForecastPerformanceCohortDefinition(
        cohort_key=_COHORT_KEY,
        version_sequence=0,
        attribution_kind=ForecastAttributionKind.AGGREGATE_SURVEY_CONSENSUS,
        originator_publisher_source_key=_PUBLISHER_SOURCE_KEY,
        target_key=_TARGET_KEY,
        forecast_type=ForecastType.NUMERIC_POINT,
        horizon_category="FAD-SAME-MEETING",
        protocol_key=_PROTOCOL_KEY,
        protocol_version_sequence=0,
        evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        duplicate_selection_policy=(
            ForecastPerformanceDuplicateSelectionPolicy.EARLIEST_QUALIFYING_ISSUE
        ),
        availability=_REGISTERED_AT,
        rationale=(
            "Every Bank of Canada Market Participants Survey forecast of the policy-rate "
            "level after a specified, scheduled Fixed Announcement Date meeting, evaluated "
            "under the FIRST-RELEASED outcome via boc-rate-fad-protocol -- the real pilot "
            "population this codebase currently holds (Section 19 Dataset A)."
        ),
    )


def _methodology() -> ForecastPerformanceMethodology:
    return ForecastPerformanceMethodology(
        methodology_key=_METHODOLOGY_KEY,
        version_sequence=0,
        cohort_key=_COHORT_KEY,
        cohort_version_sequence=0,
        missing_data_policy=ForecastPerformanceMissingDataPolicy.EXCLUDE_FROM_DENOMINATOR,
        algorithm_version="fx66_v1",
        availability=_REGISTERED_AT,
        rationale=(
            "Descriptive-only methodology: no benchmark pinned (none admissible for this "
            "single real pilot observation), MAE/mean-signed-error/RMSE computed directly "
            "from FX-65's own already-computed evaluation results."
        ),
    )


async def main(dry_run: bool) -> None:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    now = _now()

    async with session_factory() as session:
        performance_repo = SqlAlchemyForecastPerformanceRepository(session)
        evaluation_repo = SqlAlchemyForecastEvaluationRepository(session)
        forecast_repo = SqlAlchemyStructuredForecastRepository(session)
        outcome_repo = SqlAlchemyForecastOutcomeRepository(session)

        cohort_result = await DefineForecastPerformanceCohort(performance_repo)(
            _cohort(), dry_run=dry_run
        )
        print(f"{_COHORT_KEY}: {cohort_result.outcome.value}")

        methodology_result = await DefineForecastPerformanceMethodology(performance_repo)(
            _methodology(), dry_run=dry_run
        )
        print(f"{_METHODOLOGY_KEY}: {methodology_result.outcome.value}")

        if dry_run:
            print("--dry-run: stopping before population build (nothing above was written either).")
            return

        build_population = BuildForecastPerformancePopulationAsOf(
            evaluation_repo, forecast_repo, outcome_repo
        )
        population = await build_population(_cohort(), _KNOWLEDGE_CUTOFF)
        print(
            f"population: {len(population.accepted)} accepted, "
            f"{len(population.exclusions)} excluded, "
            f"{population.raw_candidate_count} raw candidates"
        )

        diagnostics = AssessForecastPerformanceEvidence()(population)
        print(f"sample_adequacy: {diagnostics.sample_adequacy.value}")
        print(f"unique_target_event_count: {diagnostics.unique_target_event_count}")
        if diagnostics.sample_adequacy is ForecastPerformanceSampleAdequacy.INSUFFICIENT_DATA:
            print(
                "EVIDENCE_INSUFFICIENT_FOR_SKILL_INFERENCE: this cohort has "
                f"{diagnostics.accepted_count} eligible forecast(s) and "
                f"{diagnostics.unique_target_event_count} distinct evaluated event(s). "
                "No claim of demonstrated forecasting skill is made."
            )

        numeric_summary, categorical_summary, comparison = CalculateForecastPerformance()(
            population
        )
        if numeric_summary is not None:
            print(
                f"descriptive MAE={numeric_summary.mean_absolute_error}"
                f"{numeric_summary.unit} mean_signed_error={numeric_summary.mean_signed_error}"
                f"{numeric_summary.unit} RMSE={numeric_summary.root_mean_squared_error}"
                f"{numeric_summary.unit}"
            )
        print(f"benchmark: {comparison.status.value}")

        snapshot_candidate = ForecastPerformanceSnapshot(
            snapshot_key=_SNAPSHOT_KEY,
            revision_sequence=0,
            methodology_key=_METHODOLOGY_KEY,
            methodology_version_sequence=0,
            cohort_key=_COHORT_KEY,
            cohort_version_sequence=0,
            evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
            members=tuple(
                ForecastPerformanceSnapshotMember(
                    evaluation_key=m.evaluation.evaluation_key,
                    evaluation_revision_sequence=m.evaluation.revision_sequence,
                    forecast_claim_key=m.evaluation.forecast_claim_key,
                    forecast_revision_sequence=m.evaluation.forecast_revision_sequence,
                    outcome_key=m.evaluation.outcome_key,
                    outcome_revision_sequence=m.evaluation.outcome_revision_sequence,
                )
                for m in population.accepted
            ),
            exclusions=population.exclusions,
            benchmark_comparison=comparison,
            diagnostics=diagnostics,
            knowledge_cutoff=_KNOWLEDGE_CUTOFF,
            availability=now,
            algorithm_version="fx66_v1",
            numeric_summary=numeric_summary,
            categorical_summary=categorical_summary,
        )
        record_snapshot = RecordForecastPerformanceSnapshot(performance_repo)
        snapshot_result = await record_snapshot(snapshot_candidate)
        print(f"{_SNAPSHOT_KEY}: {snapshot_result.outcome.value}")

        get_as_of = GetForecastPerformanceSnapshotAsOf(performance_repo)
        production_resolution = await get_as_of(_SNAPSHOT_KEY, now)
        print(f"production PIT read: {'FOUND' if production_resolution.snapshot else 'NOT FOUND'}")

        research_view = GetRetrospectiveForecastPerformanceResearchView(performance_repo)
        research_result = await research_view(_SNAPSHOT_KEY, now)
        print(
            f"retrospective research view: "
            f"{'FOUND' if research_result.snapshot is not None else 'NOT FOUND'}, "
            f"is_retrospective={research_result.is_retrospective}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))
