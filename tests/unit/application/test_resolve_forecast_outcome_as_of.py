"""FX-65 Section 6: tests for `ResolveForecastOutcomeAsOf` -- the
three vintage-selection policies and the four resolution statuses."""

from datetime import UTC, datetime
from decimal import Decimal

from forex_agent.application.use_cases.record_forecast_outcome import RecordForecastOutcome
from forex_agent.application.use_cases.resolve_forecast_outcome_as_of import (
    ResolveForecastOutcomeAsOf,
)
from forex_agent.application.use_cases.validate_forecast_outcome_candidate import (
    ForecastOutcomeCandidate,
)
from forex_agent.domain.forecast_evidence_kind import ForecastEvidenceKind
from forex_agent.domain.forecast_outcome_resolution_status import ForecastOutcomeResolutionStatus
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.forecast_target_period_kind import ForecastTargetPeriodKind
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.outcome_vintage_selection_policy import OutcomeVintageSelectionPolicy
from forex_agent.domain.timestamps import UtcTimestamp
from tests.fakes.forecast_outcome_repository import FakeForecastOutcomeRepository


def _ts(day: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, day, tzinfo=UTC))


def _candidate(**overrides: object) -> ForecastOutcomeCandidate:
    defaults: dict[str, object] = {
        "outcome_key": "US-CPI-2026-01",
        "availability": _ts(5),
        "definition_key": "US-CPI-OUTCOME",
        "definition_version_sequence": 0,
        "target_period_kind": ForecastTargetPeriodKind.CALENDAR_MONTH,
        "calendar_year": 2026,
        "calendar_month": 1,
        "outcome_type": ForecastType.NUMERIC_POINT,
        "evidence_kind": ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
        "evidence_description": "First release",
        "document_identifier": "CPI-REL-1",
        "provenance_mode": ForecastProvenanceMode.PRODUCTION_OBSERVED,
        "reviewed_by": "FTA research operator",
        "review_method": "Direct review",
        "reviewed_at": _ts(5),
        "numeric_value": Decimal("2.0"),
        "unit": "PERCENT",
    }
    defaults.update(overrides)
    return ForecastOutcomeCandidate(**defaults)  # type: ignore[arg-type]


async def test_outcome_never_recorded_is_unavailable() -> None:
    repo = FakeForecastOutcomeRepository()
    resolve = ResolveForecastOutcomeAsOf(repo)

    result = await resolve("NEVER-RECORDED", OutcomeVintageSelectionPolicy.FIRST_RELEASE, _ts(10))

    assert result.status is ForecastOutcomeResolutionStatus.OUTCOME_UNAVAILABLE
    assert result.vintage is None


async def test_recorded_but_not_yet_as_of_requested_instant_is_not_yet_matured() -> None:
    repo = FakeForecastOutcomeRepository()
    record = RecordForecastOutcome(repo)
    await record(_candidate(availability=_ts(5)))
    resolve = ResolveForecastOutcomeAsOf(repo)

    result = await resolve("US-CPI-2026-01", OutcomeVintageSelectionPolicy.FIRST_RELEASE, _ts(3))

    assert result.status is ForecastOutcomeResolutionStatus.NOT_YET_MATURED


async def test_first_release_never_replaced_by_later_revision() -> None:
    repo = FakeForecastOutcomeRepository()
    record = RecordForecastOutcome(repo)
    await record(_candidate(availability=_ts(5), numeric_value=Decimal("2.0")))
    await record(
        _candidate(
            availability=_ts(20), numeric_value=Decimal("2.2"), document_identifier="CPI-REL-2"
        )
    )
    resolve = ResolveForecastOutcomeAsOf(repo)

    result = await resolve("US-CPI-2026-01", OutcomeVintageSelectionPolicy.FIRST_RELEASE, _ts(25))

    assert result.status is ForecastOutcomeResolutionStatus.OUTCOME_AVAILABLE
    assert result.vintage is not None
    assert result.vintage.numeric_value == Decimal("2.0")


async def test_latest_available_as_of_selects_the_most_recent_qualifying_revision() -> None:
    repo = FakeForecastOutcomeRepository()
    record = RecordForecastOutcome(repo)
    await record(_candidate(availability=_ts(5), numeric_value=Decimal("2.0")))
    await record(
        _candidate(
            availability=_ts(20), numeric_value=Decimal("2.2"), document_identifier="CPI-REL-2"
        )
    )
    resolve = ResolveForecastOutcomeAsOf(repo)

    before_revision = await resolve(
        "US-CPI-2026-01", OutcomeVintageSelectionPolicy.LATEST_AVAILABLE_AS_OF, _ts(10)
    )
    after_revision = await resolve(
        "US-CPI-2026-01", OutcomeVintageSelectionPolicy.LATEST_AVAILABLE_AS_OF, _ts(25)
    )

    assert before_revision.vintage is not None
    assert before_revision.vintage.numeric_value == Decimal("2.0")
    assert after_revision.vintage is not None
    assert after_revision.vintage.numeric_value == Decimal("2.2")


async def test_fixed_release_vintage_requires_pinned_revision() -> None:
    repo = FakeForecastOutcomeRepository()
    record = RecordForecastOutcome(repo)
    await record(_candidate())
    resolve = ResolveForecastOutcomeAsOf(repo)

    result = await resolve(
        "US-CPI-2026-01", OutcomeVintageSelectionPolicy.FIXED_RELEASE_VINTAGE, _ts(10)
    )

    assert result.status is ForecastOutcomeResolutionStatus.OUTCOME_AMBIGUOUS


async def test_fixed_release_vintage_resolves_the_pinned_revision() -> None:
    repo = FakeForecastOutcomeRepository()
    record = RecordForecastOutcome(repo)
    await record(_candidate(availability=_ts(5), numeric_value=Decimal("2.0")))
    await record(
        _candidate(
            availability=_ts(20), numeric_value=Decimal("2.2"), document_identifier="CPI-REL-2"
        )
    )
    resolve = ResolveForecastOutcomeAsOf(repo)

    result = await resolve(
        "US-CPI-2026-01",
        OutcomeVintageSelectionPolicy.FIXED_RELEASE_VINTAGE,
        _ts(25),
        fixed_revision_sequence=0,
    )

    assert result.vintage is not None
    assert result.vintage.numeric_value == Decimal("2.0")
