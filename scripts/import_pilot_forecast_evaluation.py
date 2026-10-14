"""FX-65 Section 15: records ONE controlled, real-source pilot
evaluation against a live Postgres -- NOT a live outcome-provider
adapter (none is authorized by this story).

**Worked example (Section 15's own named priority #1, Bank of
Canada)**: the Bank of Canada's own Market Participants Survey, Q3
2024 round (published 2024-11-04; conducted 2024-09-18 to 2024-09-27;
28 of ~30 respondents answered the December 2024 policy-rate
question): median overnight-rate forecast for December 2024 = 3.75%.
Independently cross-checked, via WebFetch against the Bank's own
published survey results page, on 2026-10-13. Secondary corroboration:
<https://www.canadianrealestatemagazine.ca/news/boc-market-participants-survey-q3-2024/>.

The REAL outcome: the Bank of Canada's own Fixed Announcement Date
decision, 2024-12-11 -- the Bank reduced its target for the overnight
rate by 50 basis points to 3.25% (from 3.75%). Independently cross-
checked, via WebFetch against the Bank's own official press release,
on 2026-10-13. Secondary corroboration:
<https://www.scotiabank.com/ca/en/personal/advice-plus/features/posts.bank-of-canada-interest-rate-dec-2024.html>.

Forecast = 3.75%, observed = 3.25% -> signed error = -0.50 percentage
points, absolute error = 0.50 percentage points -- matching this
story's own Section 15 illustrative figures, now independently
verified rather than hard-coded on faith.

The underlying forecast itself did not yet exist in FX-64's own real
pilot dataset (which covered the 2025Q1 MPS round only) -- this
script records it first, as `RETROSPECTIVE_RESEARCH` (FTA is
acquiring it today, long after its own 2024-11-04 publication),
reusing the real `BANK_OF_CANADA` identity FX-62/64 already
established. Both the forecast's own authentication review AND the
outcome's own authentication review are recorded as explicit,
narrowly-scoped `EvidenceAuthenticationReview` objects (FX-65 Section
8) -- neither is manufactured; both describe the SAME human,
out-of-band review this script's own author performed before writing
this code.

Run:
    uv run python scripts/import_pilot_forecast_evaluation.py
    uv run python scripts/import_pilot_forecast_evaluation.py --dry-run

Requires:
    - `docker compose up -d db` (and `alembic upgrade head` already applied)
    - FX-62's own bootstrap already run (reuses the real `BANK_OF_CANADA`
      organization identity verbatim)
"""

import argparse
import asyncio
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import async_sessionmaker

from forex_agent.application.use_cases.assess_forecast_evaluation_admissibility import (
    AssessForecastEvaluationAdmissibility,
)
from forex_agent.application.use_cases.evaluate_structured_forecast import (
    EvaluateStructuredForecast,
)
from forex_agent.application.use_cases.get_retrospective_forecast_evaluation import (
    GetRetrospectiveForecastEvaluation,
)
from forex_agent.application.use_cases.record_forecast_evaluation_protocol import (
    RecordForecastEvaluationProtocol,
)
from forex_agent.application.use_cases.record_forecast_outcome import RecordForecastOutcome
from forex_agent.application.use_cases.record_forecast_outcome_definition import (
    RecordForecastOutcomeDefinition,
)
from forex_agent.application.use_cases.record_structured_forecast import RecordStructuredForecast
from forex_agent.application.use_cases.resolve_forecast_outcome_as_of import (
    ResolveForecastOutcomeAsOf,
)
from forex_agent.application.use_cases.validate_forecast_outcome_candidate import (
    ForecastOutcomeCandidate,
)
from forex_agent.application.use_cases.validate_structured_forecast_candidate import (
    StructuredForecastCandidate,
)
from forex_agent.domain.evidence_authentication_review import EvidenceAuthenticationReview
from forex_agent.domain.forecast_attribution_kind import ForecastAttributionKind
from forex_agent.domain.forecast_evaluation_metric import ForecastEvaluationMetric
from forex_agent.domain.forecast_evaluation_protocol import ForecastEvaluationProtocol
from forex_agent.domain.forecast_evidence_kind import ForecastEvidenceKind
from forex_agent.domain.forecast_outcome_definition import ForecastOutcomeDefinition
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.forecast_target_period_kind import ForecastTargetPeriodKind
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.outcome_vintage_selection_policy import OutcomeVintageSelectionPolicy
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.forecast_evaluation_repository import (
    SqlAlchemyForecastEvaluationRepository,
)
from forex_agent.infrastructure.db.forecast_outcome_repository import (
    SqlAlchemyForecastOutcomeRepository,
)
from forex_agent.infrastructure.db.session import get_engine
from forex_agent.infrastructure.db.structured_forecast_repository import (
    SqlAlchemyStructuredForecastRepository,
)

_FORECAST_CLAIM_KEY = "BOC-MPS-2024Q3:CA_POLICY_RATE_LEVEL_AFTER_MEETING:AGGREGATE"
_MEETING_ID = "BOC-2024-12-11"
_DEFINITION_KEY = "BOC-RATE-FAD-OUTCOME"
_OUTCOME_KEY = f"BOC-RATE-DECISION-{_MEETING_ID[4:]}"
_PROTOCOL_KEY = "boc-rate-fad-protocol"
_EVALUATION_KEY = f"EVAL:{_FORECAST_CLAIM_KEY}:{_PROTOCOL_KEY}"

# The human review itself happened ONCE, on this date -- fixed, never
# `now()`, so a repeat run of this script does not manufacture a NEW
# review event merely because the script happens to run again later.
_REVIEWED_AT = UtcTimestamp(datetime(2026, 10, 13, tzinfo=UTC))


def _ts(year: int, month: int, day: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(year, month, day, tzinfo=UTC))


def _now() -> UtcTimestamp:
    return UtcTimestamp(datetime.now(UTC))


def _forecast_candidate(now: UtcTimestamp) -> StructuredForecastCandidate:
    return StructuredForecastCandidate(
        claim_key=_FORECAST_CLAIM_KEY,
        availability=now,
        algorithm_version="fx64_v1",
        forecast_type=ForecastType.NUMERIC_POINT,
        target_key="CA_POLICY_RATE_LEVEL_AFTER_MEETING",
        target_period_kind=ForecastTargetPeriodKind.POLICY_MEETING,
        policy_meeting_identifier=_MEETING_ID,
        attribution_kind=ForecastAttributionKind.AGGREGATE_SURVEY_CONSENSUS,
        publisher_source_key="BANK_OF_CANADA",
        evidence_kind=ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
        evidence_description=(
            "Bank of Canada Market Participants Survey, Q3 2024 round (conducted 2024-09-18 to "
            "2024-09-27): median overnight rate forecast of 3.75% for December 2024, aggregated "
            "across 28 respondents, per the Bank of Canada's own published survey results page "
            "(see official_reference_url)."
        ),
        document_identifier="BOC-MPS-2024Q3",
        official_reference_url=(
            "https://www.bankofcanada.ca/2024/11/market-participants-survey-third-quarter-of-2024/"
        ),
        publisher_declared_publication_at=_ts(2024, 11, 4),
        provenance_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        original_publication_at=_ts(2024, 11, 4),
        numeric_value=Decimal("3.75"),
        unit="PERCENT",
    )


def _outcome_definition(now: UtcTimestamp) -> ForecastOutcomeDefinition:
    return ForecastOutcomeDefinition(
        definition_key=_DEFINITION_KEY,
        version_sequence=0,
        target_key="CA_POLICY_RATE_LEVEL_AFTER_MEETING",
        outcome_type=ForecastType.NUMERIC_POINT,
        provider_source_key="BANK_OF_CANADA",
        required_source_series_identifier="BOC-FIXED-ANNOUNCEMENT-DATE-PRESS-RELEASE",
        outcome_vintage_selection_policy=OutcomeVintageSelectionPolicy.FIRST_RELEASE,
        availability=now,
        supporting_definition_reference=(
            "Bank of Canada Fixed Announcement Date framework -- the Bank's own scheduled "
            "overnight-rate-target decisions, each announced via its own official press release."
        ),
    )


def _outcome_candidate(now: UtcTimestamp) -> ForecastOutcomeCandidate:
    return ForecastOutcomeCandidate(
        outcome_key=_OUTCOME_KEY,
        availability=now,
        definition_key=_DEFINITION_KEY,
        definition_version_sequence=0,
        target_period_kind=ForecastTargetPeriodKind.POLICY_MEETING,
        policy_meeting_identifier=_MEETING_ID,
        outcome_type=ForecastType.NUMERIC_POINT,
        evidence_kind=ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
        evidence_description=(
            "Bank of Canada Fixed Announcement Date decision, 2024-12-11: the Bank reduced its "
            "target for the overnight rate by 50 basis points to 3.25% (Bank Rate 3.50%, "
            "deposit rate 3.25%), per the Bank's own official press release (see "
            "official_reference_url)."
        ),
        document_identifier="BOC-FAD-2024-12-11",
        official_reference_url="https://www.bankofcanada.ca/2024/12/fad-press-release-2024-12-11/",
        provenance_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
        reviewed_by="FTA research operator (2026-10-13 session)",
        review_method=(
            "Independently cross-checked via WebFetch against the Bank of Canada's own official "
            "press release before this script was written."
        ),
        reviewed_at=_REVIEWED_AT,
        corroboration_reference=(
            "https://www.scotiabank.com/ca/en/personal/advice-plus/features/posts.bank-of-"
            "canada-interest-rate-dec-2024.html"
        ),
        numeric_value=Decimal("3.25"),
        unit="PERCENT",
    )


def _protocol(now: UtcTimestamp) -> ForecastEvaluationProtocol:
    return ForecastEvaluationProtocol(
        protocol_key=_PROTOCOL_KEY,
        version_sequence=0,
        supported_forecast_type=ForecastType.NUMERIC_POINT,
        target_key="CA_POLICY_RATE_LEVEL_AFTER_MEETING",
        outcome_definition_key=_DEFINITION_KEY,
        outcome_definition_version_sequence=0,
        outcome_vintage_selection_policy=OutcomeVintageSelectionPolicy.FIRST_RELEASE,
        metric=ForecastEvaluationMetric.NUMERIC_ERROR,
        availability=now,
        rationale=(
            "Compares the Bank of Canada Market Participants Survey's own median overnight-"
            "rate-level forecast for a specified, scheduled Fixed Announcement Date decision "
            "against the FIRST-RELEASED official outcome of that exact decision -- never a "
            "later-revised figure, since a Fixed Announcement Date decision is never itself "
            "revised after the fact. Chosen BEFORE the outcome was resolved (Section 6/7's own "
            "explicit requirement)."
        ),
    )


def _forecast_authentication_review() -> EvidenceAuthenticationReview:
    return EvidenceAuthenticationReview(
        reviewed_by="FTA research operator (2026-10-13 session)",
        review_method=(
            "Independently cross-checked via WebFetch against the Bank of Canada's own "
            "published Market Participants Survey results page before this script was written."
        ),
        reviewed_at=_REVIEWED_AT,
        corroboration_reference=(
            "https://www.canadianrealestatemagazine.ca/news/boc-market-participants-survey-q3-2024/"
        ),
    )


async def main(dry_run: bool) -> None:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    now = _now()

    async with session_factory() as session:
        forecast_repo = SqlAlchemyStructuredForecastRepository(session)
        outcome_repo = SqlAlchemyForecastOutcomeRepository(session)
        evaluation_repo = SqlAlchemyForecastEvaluationRepository(session)

        record_forecast = RecordStructuredForecast(forecast_repo)
        forecast_result = await record_forecast(
            _forecast_candidate(now), registered_at=now, dry_run=dry_run
        )
        print(
            f"{_FORECAST_CLAIM_KEY}: {forecast_result.outcome.value} "
            f"({forecast_result.eligibility.value})"
        )

        record_definition = RecordForecastOutcomeDefinition(outcome_repo)
        definition_result = await record_definition(_outcome_definition(now), dry_run=dry_run)
        print(f"{_DEFINITION_KEY}: {definition_result.outcome.value}")

        record_outcome = RecordForecastOutcome(outcome_repo)
        outcome_result = await record_outcome(_outcome_candidate(now), dry_run=dry_run)
        print(
            f"{_OUTCOME_KEY}: {outcome_result.outcome.value} ({outcome_result.eligibility.value})"
        )

        record_protocol = RecordForecastEvaluationProtocol(evaluation_repo)
        protocol_result = await record_protocol(_protocol(now), dry_run=dry_run)
        print(f"{_PROTOCOL_KEY}: {protocol_result.outcome.value}")

        if dry_run:
            print("--dry-run: stopping before evaluation (nothing above was written either).")
            return

        resolve_outcome = ResolveForecastOutcomeAsOf(outcome_repo)
        outcome_resolution = await resolve_outcome(
            _OUTCOME_KEY, OutcomeVintageSelectionPolicy.FIRST_RELEASE, now
        )
        print(f"outcome resolution: {outcome_resolution.status.value}")

        forecast_vintage = forecast_result.vintage
        assert forecast_vintage is not None

        evaluate = EvaluateStructuredForecast(
            evaluation_repo, outcome_repo, assess=AssessForecastEvaluationAdmissibility()
        )
        eval_result = await evaluate(
            evaluation_key=_EVALUATION_KEY,
            forecast_vintage=forecast_vintage,
            forecast_authentication_review=_forecast_authentication_review(),
            evaluation_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
            protocol=_protocol(now),
            outcome_key=_OUTCOME_KEY,
            algorithm_version="fx65_v1",
            availability=now,
        )
        print(f"{_EVALUATION_KEY}: {eval_result.outcome.value} ({eval_result.admissibility.value})")
        if eval_result.vintage is not None:
            result = eval_result.vintage.result
            print(f"  signed_error={result.signed_error} absolute_error={result.absolute_error}")

        research_view = GetRetrospectiveForecastEvaluation(evaluation_repo)
        research_result = await research_view(_EVALUATION_KEY, now)
        print(
            f"retrospective evaluation view: "
            f"{'FOUND' if research_result.vintage is not None else 'NOT FOUND'}, "
            f"is_retrospective={research_result.is_retrospective}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))
