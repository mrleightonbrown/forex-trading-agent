"""FX-65 Section 7: tests for `RecordForecastEvaluationProtocol`."""

from datetime import UTC, datetime

import pytest

from forex_agent.application.use_cases.record_forecast_evaluation_protocol import (
    ForecastEvaluationProtocolConflictError,
    ForecastEvaluationProtocolOutcome,
    OutOfSequenceEvaluationProtocolError,
    RecordForecastEvaluationProtocol,
)
from forex_agent.domain.forecast_evaluation_metric import ForecastEvaluationMetric
from forex_agent.domain.forecast_evaluation_protocol import ForecastEvaluationProtocol
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.outcome_vintage_selection_policy import OutcomeVintageSelectionPolicy
from forex_agent.domain.timestamps import UtcTimestamp
from tests.fakes.forecast_evaluation_repository import FakeForecastEvaluationRepository


def _ts(day: int = 1) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, day, tzinfo=UTC))


def _protocol(**overrides: object) -> ForecastEvaluationProtocol:
    defaults: dict[str, object] = {
        "protocol_key": "boc-rate-protocol",
        "version_sequence": 0,
        "supported_forecast_type": ForecastType.NUMERIC_POINT,
        "target_key": "CA_POLICY_RATE_LEVEL_AFTER_MEETING",
        "outcome_definition_key": "BOC-RATE-OUTCOME",
        "outcome_definition_version_sequence": 0,
        "outcome_vintage_selection_policy": OutcomeVintageSelectionPolicy.FIRST_RELEASE,
        "metric": ForecastEvaluationMetric.NUMERIC_ERROR,
        "availability": _ts(1),
        "rationale": "Compares MPS point forecast against the official decision outcome.",
    }
    defaults.update(overrides)
    return ForecastEvaluationProtocol(**defaults)  # type: ignore[arg-type]


async def test_first_registration_is_created() -> None:
    repo = FakeForecastEvaluationRepository()
    record = RecordForecastEvaluationProtocol(repo)

    result = await record(_protocol())

    assert result.outcome is ForecastEvaluationProtocolOutcome.CREATED


async def test_idempotent_rerun_with_a_different_availability_is_unchanged() -> None:
    repo = FakeForecastEvaluationRepository()
    record = RecordForecastEvaluationProtocol(repo)
    await record(_protocol(availability=_ts(1)))

    result = await record(_protocol(availability=_ts(9)))

    assert result.outcome is ForecastEvaluationProtocolOutcome.UNCHANGED


async def test_genuinely_different_content_at_the_same_version_is_a_conflict() -> None:
    repo = FakeForecastEvaluationRepository()
    record = RecordForecastEvaluationProtocol(repo)
    await record(_protocol())

    with pytest.raises(ForecastEvaluationProtocolConflictError):
        await record(_protocol(rationale="A completely different rationale text."))


async def test_out_of_sequence_version_is_rejected() -> None:
    repo = FakeForecastEvaluationRepository()
    record = RecordForecastEvaluationProtocol(repo)

    with pytest.raises(OutOfSequenceEvaluationProtocolError):
        await record(_protocol(version_sequence=1))
