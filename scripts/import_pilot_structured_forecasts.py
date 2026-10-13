"""FX-64 Section 16: records a small, EXPLICITLY CONTROLLED dataset of
structured-forecast pilot examples against a live Postgres -- NOT a
live acquisition adapter (none is authorized by this story); every
value below was verified against each source's own public
documentation, cited in each record's own `official_reference_url`/
`document_identifier`, immediately before this script was written.

Real, independently-verified examples (all RETROSPECTIVE_RESEARCH --
FTA is acquiring every one of these TODAY, long after its own real
publication date; this story authorizes no live/contemporaneous
acquisition adapter, so no genuine PRODUCTION_OBSERVED pilot example
exists -- see this story's own completion report for why that is an
honest architectural gap, not an oversight):

1. ECB Survey of Professional Forecasters, Q1 2025 round (published
   2025-01-31): HICP annual-average inflation forecast for 2025 =
   2.1%, 60 respondents.
2. ECB Survey of Professional Forecasters, Q2 2025 round (published
   2025-04-22): HICP annual-average inflation forecast for 2025 =
   2.2%, 54 respondents -- Section 5's own "separate forecast issue"
   rule demonstrated with REAL data: this is a genuinely NEW survey
   round, a DISTINCT claim from #1, never a correction/overwrite of
   it, even though both concern the identical target+period.
3. Bank of Canada Market Participants Survey, Q1 2025 round
   (published 2025-04-28, conducted 2025-03-13 to 2025-03-20): median
   overnight rate forecast for the 2025-12-10 Governing Council
   decision = 2.25%.
4. The SAME Bank of Canada MPS Q1 2025 round: median real GDP growth
   forecast, year-over-year, as of the end of 2025 = 1.0% -- a
   DIFFERENT variable family (GDP_GROWTH, not POLICY_RATE) from the
   SAME document, demonstrating one evidence reference legitimately
   supporting more than one claim.

Every real example above uses `ForecastAttributionKind.AGGREGATE_
SURVEY_CONSENSUS` -- the architect's own explicit concern: the
publishing institution (ECB/the Bank of Canada) is NEVER recorded as
the forecaster for an aggregate survey median.

One additional, CLEARLY LABELED SYNTHETIC example (prefixed
`SYNTHETIC-ILLUSTRATIVE` in its own `claim_key`, never presented as a
real historical event) demonstrates a genuine WITHIN-CLAIM correction
-- the same survey round's own transcribed figure corrected after a
second, independent review of the source document, via a NEW vintage
under DIFFERENT evidence (never a mutation of the original).

Run:
    uv run python scripts/import_pilot_structured_forecasts.py
    uv run python scripts/import_pilot_structured_forecasts.py --dry-run

Requires:
    - `docker compose up -d db` (and `alembic upgrade head` already applied)
    - FX-62's own bootstrap already run (reuses the real `EUROPEAN_CENTRAL_BANK`/
      `BANK_OF_CANADA` organization identities verbatim)
"""

import argparse
import asyncio
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import async_sessionmaker

from forex_agent.application.use_cases.record_structured_forecast import (
    RecordStructuredForecast,
)
from forex_agent.application.use_cases.validate_structured_forecast_candidate import (
    StructuredForecastCandidate,
)
from forex_agent.domain.forecast_attribution_kind import ForecastAttributionKind
from forex_agent.domain.forecast_evidence_kind import ForecastEvidenceKind
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.forecast_target_period_kind import ForecastTargetPeriodKind
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.session import get_engine
from forex_agent.infrastructure.db.structured_forecast_repository import (
    SqlAlchemyStructuredForecastRepository,
)


def _ts(year: int, month: int, day: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(year, month, day, tzinfo=UTC))


def _now() -> UtcTimestamp:
    return UtcTimestamp(datetime.now(UTC))


_SYNTHETIC_CLAIM_KEY = "SYNTHETIC-ILLUSTRATIVE:EA_HICP_YOY_ANNUAL_AVERAGE:AGGREGATE-DEMO"


def _pilot_candidates(now: UtcTimestamp) -> tuple[StructuredForecastCandidate, ...]:
    return (
        # 1. ECB SPF Q1 2025 -- REAL.
        StructuredForecastCandidate(
            claim_key="ECB-SPF-2025Q1:EA_HICP_YOY_ANNUAL_AVERAGE:AGGREGATE",
            availability=now,
            algorithm_version="fx64_v1",
            forecast_type=ForecastType.NUMERIC_POINT,
            target_key="EA_HICP_YOY_ANNUAL_AVERAGE",
            target_period_kind=ForecastTargetPeriodKind.CALENDAR_YEAR,
            calendar_year=2025,
            attribution_kind=ForecastAttributionKind.AGGREGATE_SURVEY_CONSENSUS,
            publisher_source_key="EUROPEAN_CENTRAL_BANK",
            evidence_kind=ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
            evidence_description=(
                "ECB Survey of Professional Forecasters, Q1 2025 round: HICP annual-average "
                "inflation forecast for calendar year 2025, aggregated across 60 respondents. "
                "Verified directly against the ECB's own published survey results page."
            ),
            document_identifier="ECB-SPF-2025Q1",
            official_reference_url=(
                "https://www.ecb.europa.eu/stats/ecb_surveys/survey_of_professional_"
                "forecasters/html/ecb.spf2025q1~12ccd2307f.en.html"
            ),
            publisher_declared_publication_at=_ts(2025, 1, 31),
            provenance_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
            original_publication_at=_ts(2025, 1, 31),
            numeric_value=Decimal("2.1"),
            unit="PERCENT_YOY",
        ),
        # 2. ECB SPF Q2 2025 -- REAL, a DISTINCT claim from #1 (Section 5).
        StructuredForecastCandidate(
            claim_key="ECB-SPF-2025Q2:EA_HICP_YOY_ANNUAL_AVERAGE:AGGREGATE",
            availability=now,
            algorithm_version="fx64_v1",
            forecast_type=ForecastType.NUMERIC_POINT,
            target_key="EA_HICP_YOY_ANNUAL_AVERAGE",
            target_period_kind=ForecastTargetPeriodKind.CALENDAR_YEAR,
            calendar_year=2025,
            attribution_kind=ForecastAttributionKind.AGGREGATE_SURVEY_CONSENSUS,
            publisher_source_key="EUROPEAN_CENTRAL_BANK",
            evidence_kind=ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
            evidence_description=(
                "ECB Survey of Professional Forecasters, Q2 2025 round: HICP annual-average "
                "inflation forecast for calendar year 2025, aggregated across 54 respondents. "
                "Verified directly against the ECB's own published press release."
            ),
            document_identifier="ECB-SPF-2025Q2",
            official_reference_url=(
                "https://www.ecb.europa.eu/press/pr/date/2025/html/ecb.pr250422~a289ea4ebf.en.html"
            ),
            publisher_declared_publication_at=_ts(2025, 4, 22),
            provenance_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
            original_publication_at=_ts(2025, 4, 22),
            numeric_value=Decimal("2.2"),
            unit="PERCENT_YOY",
        ),
        # 3. Bank of Canada MPS Q1 2025, policy rate -- REAL.
        StructuredForecastCandidate(
            claim_key="BOC-MPS-2025Q1:CA_POLICY_RATE_LEVEL_AFTER_MEETING:AGGREGATE",
            availability=now,
            algorithm_version="fx64_v1",
            forecast_type=ForecastType.NUMERIC_POINT,
            target_key="CA_POLICY_RATE_LEVEL_AFTER_MEETING",
            target_period_kind=ForecastTargetPeriodKind.POLICY_MEETING,
            policy_meeting_identifier="BOC-2025-12-10",
            attribution_kind=ForecastAttributionKind.AGGREGATE_SURVEY_CONSENSUS,
            publisher_source_key="BANK_OF_CANADA",
            evidence_kind=ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
            evidence_description=(
                "Bank of Canada Market Participants Survey, Q1 2025 round (conducted "
                "2025-03-13 to 2025-03-20): median overnight rate forecast of 2.25% for the "
                "scheduled 2025-12-10 Governing Council decision, aggregated across "
                "approximately 30 respondents. Verified directly against the Bank of Canada's "
                "own published survey results page; the 2025-12-10 meeting date is "
                "independently grounded by the Bank's own fixed announcement-date press "
                "release for that decision."
            ),
            document_identifier="BOC-MPS-2025Q1",
            official_reference_url=(
                "https://www.bankofcanada.ca/2025/04/market-participants-survey-first-"
                "quarter-of-2025/"
            ),
            publisher_declared_publication_at=_ts(2025, 4, 28),
            provenance_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
            original_publication_at=_ts(2025, 4, 28),
            numeric_value=Decimal("2.25"),
            unit="PERCENT",
        ),
        # 4. The SAME BoC MPS Q1 2025 round, GDP growth -- REAL.
        StructuredForecastCandidate(
            claim_key="BOC-MPS-2025Q1:CA_REAL_GDP_GROWTH_YOY_YEAR_END:AGGREGATE",
            availability=now,
            algorithm_version="fx64_v1",
            forecast_type=ForecastType.NUMERIC_POINT,
            target_key="CA_REAL_GDP_GROWTH_YOY_YEAR_END",
            target_period_kind=ForecastTargetPeriodKind.CALENDAR_YEAR,
            calendar_year=2025,
            attribution_kind=ForecastAttributionKind.AGGREGATE_SURVEY_CONSENSUS,
            publisher_source_key="BANK_OF_CANADA",
            evidence_kind=ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
            evidence_description=(
                "Bank of Canada Market Participants Survey, Q1 2025 round: median real GDP "
                "growth forecast of 1.0% year-over-year as of the end of calendar year 2025, "
                "aggregated across approximately 30 respondents. Verified directly against "
                "the Bank of Canada's own published survey results page -- the SAME source "
                "document as claim #3 above, supporting a genuinely different target."
            ),
            document_identifier="BOC-MPS-2025Q1",
            official_reference_url=(
                "https://www.bankofcanada.ca/2025/04/market-participants-survey-first-"
                "quarter-of-2025/"
            ),
            publisher_declared_publication_at=_ts(2025, 4, 28),
            provenance_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
            original_publication_at=_ts(2025, 4, 28),
            numeric_value=Decimal("1.0"),
            unit="PERCENT_YOY",
        ),
    )


def _synthetic_original_candidate() -> StructuredForecastCandidate:
    """A within-claim correction demo, CLEARLY labeled, never
    presented as a real historical event. Revision 0 -- uses FIXED
    historical timestamps (unlike every real example above, which
    always uses `now`) so the two synthetic steps stay in a fixed,
    readable order; see `main`'s own idempotency guard for why this
    means the demo is skipped, not re-submitted, on a repeat run."""
    return StructuredForecastCandidate(
        claim_key=_SYNTHETIC_CLAIM_KEY,
        availability=_ts(2025, 2, 1),
        algorithm_version="fx64_v1",
        forecast_type=ForecastType.NUMERIC_POINT,
        target_key="EA_HICP_YOY_ANNUAL_AVERAGE",
        target_period_kind=ForecastTargetPeriodKind.CALENDAR_YEAR,
        calendar_year=2025,
        attribution_kind=ForecastAttributionKind.AGGREGATE_SURVEY_CONSENSUS,
        publisher_source_key="EUROPEAN_CENTRAL_BANK",
        evidence_kind=ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
        evidence_description=(
            "SYNTHETIC/ILLUSTRATIVE ONLY -- not a real historical event. Simulates an "
            "initial transcription of a (fictitious) results table."
        ),
        document_identifier="SYNTHETIC-DOC-V1",
        provenance_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED,
        numeric_value=Decimal("2.0"),
        unit="PERCENT_YOY",
    )


def _synthetic_correction_candidate() -> StructuredForecastCandidate:
    """Revision 1 of the SAME synthetic claim above -- a genuine
    WITHIN-CLAIM correction, under DIFFERENT evidence (Section 12/13:
    a correction is never a mutation; it is a NEW vintage, and the
    evidence object itself must differ for it to be treated as a
    legitimate correction rather than a determinism violation)."""
    return StructuredForecastCandidate(
        claim_key="SYNTHETIC-ILLUSTRATIVE:EA_HICP_YOY_ANNUAL_AVERAGE:AGGREGATE-DEMO",
        availability=_ts(2025, 2, 5),
        algorithm_version="fx64_v1",
        forecast_type=ForecastType.NUMERIC_POINT,
        target_key="EA_HICP_YOY_ANNUAL_AVERAGE",
        target_period_kind=ForecastTargetPeriodKind.CALENDAR_YEAR,
        calendar_year=2025,
        attribution_kind=ForecastAttributionKind.AGGREGATE_SURVEY_CONSENSUS,
        publisher_source_key="EUROPEAN_CENTRAL_BANK",
        evidence_kind=ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
        evidence_description=(
            "SYNTHETIC/ILLUSTRATIVE ONLY -- not a real historical event. Simulates a second, "
            "independent re-check of the (fictitious) results table revealing a transcription "
            "error in the original reading."
        ),
        document_identifier="SYNTHETIC-DOC-V1-RECHECKED",
        provenance_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED,
        numeric_value=Decimal("2.2"),
        unit="PERCENT_YOY",
    )


async def main(dry_run: bool) -> None:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    now = _now()

    async with session_factory() as session:
        repository = SqlAlchemyStructuredForecastRepository(session)
        record = RecordStructuredForecast(repository)

        for candidate in _pilot_candidates(now):
            result = await record(candidate, registered_at=now, dry_run=dry_run)
            print(f"{candidate.claim_key}: {result.outcome.value} ({result.eligibility.value})")
            if result.reason:
                print(f"  reason: {result.reason}")

        # The synthetic correction demo uses FIXED historical
        # timestamps (unlike the real examples above, which always
        # use `now`) so its own two steps stay in a fixed, readable
        # order -- which means, unlike every real example above, a
        # REPEATED run of this specific two-step demo is not itself
        # idempotent (a second run's own first step would be
        # correctly rejected as backdated relative to the first run's
        # own already-stored correction). This is the PIT-ordering
        # safeguard working exactly as designed, not a bug; detected
        # here and the whole two-step demo is skipped on a repeat
        # run, rather than letting either step fail.
        existing_synthetic_claim = await repository.get_claim(_SYNTHETIC_CLAIM_KEY)
        if existing_synthetic_claim is not None and not dry_run:
            print(f"{_SYNTHETIC_CLAIM_KEY}: already recorded in a previous run, skipping")
            return

        original_result = await record(
            _synthetic_original_candidate(), registered_at=now, dry_run=dry_run
        )
        print(
            f"{_SYNTHETIC_CLAIM_KEY}: {original_result.outcome.value} "
            f"({original_result.eligibility.value})"
        )

        correction_result = await record(
            _synthetic_correction_candidate(),
            registered_at=now,
            correction_reason="SYNTHETIC DEMO: initial transcription misread 2.0% instead of 2.2%",
            dry_run=dry_run,
        )
        print(
            f"{_SYNTHETIC_CLAIM_KEY} [correction]: "
            f"{correction_result.outcome.value} ({correction_result.eligibility.value})"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))
