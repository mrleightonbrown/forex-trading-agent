"""FX-67 Section 18: read-only CLI inspection of an already-recorded
`ForecastPerformanceSnapshot` -- the "thin CLI... sufficient if
consistent with the repository" presentation surface Section 15
explicitly allows instead of a new web dashboard. Performs ZERO
writes of any kind (Section 16): every route below only ever calls
`Get*`/`List*`/`Inspect*` read use cases.

Default arguments point at the ONE real snapshot this codebase holds
(`scripts/demonstrate_forecast_performance_pilot.py`'s own real Bank
of Canada pilot, reused verbatim here, never redefined independently
-- a second, drifting copy of that key would itself be a bug)."""

import argparse
import asyncio
import json
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import async_sessionmaker

from forex_agent.application.use_cases.build_forecast_performance_population_as_of import (
    BuildForecastPerformancePopulationAsOf,
)
from forex_agent.application.use_cases.forecast_performance_inspection_support import (
    ForecastPerformanceInspectionMode,
)
from forex_agent.application.use_cases.get_forecast_performance_benchmark_inspection import (
    GetForecastPerformanceBenchmarkInspection,
)
from forex_agent.application.use_cases.get_forecast_performance_exclusions import (
    GetForecastPerformanceExclusions,
)
from forex_agent.application.use_cases.get_forecast_performance_inspection import (
    GetForecastPerformanceInspection,
)
from forex_agent.application.use_cases.get_forecast_performance_members import (
    GetForecastPerformanceMembers,
)
from forex_agent.application.use_cases.get_forecast_performance_revision_inspection import (
    GetForecastPerformanceRevisionInspection,
)
from forex_agent.application.use_cases.inspect_forecast_performance_pending_revisions import (
    InspectForecastPerformancePendingRevisions,
)
from forex_agent.apps.cli.forecast_performance_inspection_report import (
    render_forecast_performance_inspection_report,
)
from forex_agent.apps.cli.forecast_performance_inspection_view import (
    build_forecast_performance_inspection_view,
)
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
from forex_agent.infrastructure.db.source_registry_repository import (
    SqlAlchemySourceRegistryRepository,
)
from forex_agent.infrastructure.db.structured_forecast_repository import (
    SqlAlchemyStructuredForecastRepository,
)

#: The real pilot's own exact keys (`scripts/demonstrate_forecast_
#: performance_pilot.py`) -- reused verbatim, never redefined.
_DEFAULT_SNAPSHOT_KEY = (
    "PERF:BOC-MPS-FAD-SAME-MEETING-COHORT:BOC-MPS-FAD-SAME-MEETING-COHORT-methodology"
)
_PAGE_LIMIT = 50


def _now() -> UtcTimestamp:
    return UtcTimestamp(datetime.now(UTC))


async def main(
    snapshot_key: str,
    mode: ForecastPerformanceInspectionMode,
    as_of: UtcTimestamp,
    administrative_as_of: UtcTimestamp,
    as_json: bool,
) -> None:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    async with session_factory() as session:
        performance_repo = SqlAlchemyForecastPerformanceRepository(session)
        evaluation_repo = SqlAlchemyForecastEvaluationRepository(session)
        forecast_repo = SqlAlchemyStructuredForecastRepository(session)
        outcome_repo = SqlAlchemyForecastOutcomeRepository(session)
        registry_repo = SqlAlchemySourceRegistryRepository(session)

        get_inspection = GetForecastPerformanceInspection(
            performance_repo, evaluation_repo, registry_repo
        )
        inspection = await get_inspection(snapshot_key, mode, as_of)

        get_members = GetForecastPerformanceMembers(
            performance_repo, evaluation_repo, forecast_repo, outcome_repo, registry_repo
        )
        members = await get_members(snapshot_key, mode, as_of, limit=_PAGE_LIMIT)

        get_exclusions = GetForecastPerformanceExclusions(performance_repo)
        exclusions = await get_exclusions(snapshot_key, mode, as_of, limit=_PAGE_LIMIT)

        get_benchmark = GetForecastPerformanceBenchmarkInspection(performance_repo)
        benchmark_inspection = await get_benchmark(snapshot_key, mode, as_of)

        build_population = BuildForecastPerformancePopulationAsOf(
            evaluation_repo, forecast_repo, outcome_repo
        )
        pending_revisions = InspectForecastPerformancePendingRevisions(build_population)
        get_revisions = GetForecastPerformanceRevisionInspection(
            performance_repo, pending_revisions
        )
        revision_inspection = await get_revisions(
            snapshot_key, mode, as_of, administrative_as_of=administrative_as_of
        )

        if as_json:
            view = build_forecast_performance_inspection_view(
                inspection,
                members=members,
                exclusions=exclusions,
                benchmark_inspection=benchmark_inspection,
                revision_inspection=revision_inspection,
            )
            print(json.dumps(view, indent=2))
        else:
            report = render_forecast_performance_inspection_report(
                inspection,
                members=members,
                exclusions=exclusions,
                benchmark_inspection=benchmark_inspection,
                revision_inspection=revision_inspection,
            )
            print(report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-key", default=_DEFAULT_SNAPSHOT_KEY)
    parser.add_argument(
        "--mode", choices=["PRODUCTION", "RETROSPECTIVE_RESEARCH"], default="RETROSPECTIVE_RESEARCH"
    )
    parser.add_argument("--as-of", default=None, help="ISO 8601; defaults to now")
    parser.add_argument("--administrative-as-of", default=None, help="ISO 8601; defaults to now")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    resolved_as_of = UtcTimestamp(datetime.fromisoformat(args.as_of)) if args.as_of else _now()
    resolved_administrative_as_of = (
        UtcTimestamp(datetime.fromisoformat(args.administrative_as_of))
        if args.administrative_as_of
        else _now()
    )
    asyncio.run(
        main(
            args.snapshot_key,
            ForecastPerformanceInspectionMode(args.mode),
            resolved_as_of,
            resolved_administrative_as_of,
            args.json,
        )
    )
