"""FX-65 Section 4: tests for `RecordForecastOutcomeDefinition`."""

from datetime import UTC, datetime

import pytest

from forex_agent.application.use_cases.record_forecast_outcome_definition import (
    ForecastOutcomeDefinitionConflictError,
    ForecastOutcomeDefinitionOutcome,
    OutOfSequenceOutcomeDefinitionError,
    RecordForecastOutcomeDefinition,
)
from forex_agent.domain.forecast_outcome_definition import ForecastOutcomeDefinition
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.outcome_vintage_selection_policy import OutcomeVintageSelectionPolicy
from forex_agent.domain.timestamps import UtcTimestamp
from tests.fakes.forecast_outcome_repository import FakeForecastOutcomeRepository


def _ts(day: int = 1) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, day, tzinfo=UTC))


def _definition(**overrides: object) -> ForecastOutcomeDefinition:
    defaults: dict[str, object] = {
        "definition_key": "BOC-RATE-OUTCOME",
        "version_sequence": 0,
        "target_key": "CA_POLICY_RATE_LEVEL_AFTER_MEETING",
        "outcome_type": ForecastType.NUMERIC_POINT,
        "provider_source_key": "BANK_OF_CANADA",
        "required_source_series_identifier": "BOC-RATE-ANNOUNCEMENT",
        "outcome_vintage_selection_policy": OutcomeVintageSelectionPolicy.FIRST_RELEASE,
        "availability": _ts(1),
        "supporting_definition_reference": "Bank of Canada FAD methodology",
    }
    defaults.update(overrides)
    return ForecastOutcomeDefinition(**defaults)  # type: ignore[arg-type]


async def test_first_registration_is_created() -> None:
    repo = FakeForecastOutcomeRepository()
    record = RecordForecastOutcomeDefinition(repo)

    result = await record(_definition())

    assert result.outcome is ForecastOutcomeDefinitionOutcome.CREATED


async def test_idempotent_rerun_with_a_different_availability_is_unchanged() -> None:
    """Regression test: a bootstrap/pilot script re-run supplies a
    FRESH `now()` on every run. That is not a substantive content
    change and must never be treated as a conflict -- caught live
    when the real pilot script crashed on its own second run before
    this fix."""
    repo = FakeForecastOutcomeRepository()
    record = RecordForecastOutcomeDefinition(repo)
    await record(_definition(availability=_ts(1)))

    result = await record(_definition(availability=_ts(9)))

    assert result.outcome is ForecastOutcomeDefinitionOutcome.UNCHANGED


async def test_genuinely_different_content_at_the_same_version_is_a_conflict() -> None:
    repo = FakeForecastOutcomeRepository()
    record = RecordForecastOutcomeDefinition(repo)
    await record(_definition())

    with pytest.raises(ForecastOutcomeDefinitionConflictError):
        await record(_definition(required_source_series_identifier="SOMETHING-ELSE"))


async def test_out_of_sequence_version_is_rejected() -> None:
    repo = FakeForecastOutcomeRepository()
    record = RecordForecastOutcomeDefinition(repo)

    with pytest.raises(OutOfSequenceOutcomeDefinitionError):
        await record(_definition(version_sequence=1))


async def test_revision_added_for_the_next_sequential_version() -> None:
    repo = FakeForecastOutcomeRepository()
    record = RecordForecastOutcomeDefinition(repo)
    await record(_definition())

    result = await record(
        _definition(
            version_sequence=1,
            supporting_definition_reference="Revised methodology reference",
            correction_reason="clarified methodology wording",
        )
    )

    assert result.outcome is ForecastOutcomeDefinitionOutcome.REVISION_ADDED
