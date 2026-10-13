"""FX-63 Section 13.A/B: tests for `RecordSourceOperationalObservation`
-- idempotent duplicate-delivery handling, distinct retries, and no
inferred publisher judgment anywhere in this use case's own surface."""

from datetime import UTC, datetime

import pytest

from forex_agent.application.use_cases.record_source_operational_observation import (
    RecordSourceOperationalObservation,
    SourceOperationalObservationOutcome,
)
from forex_agent.domain.source_acquisition_outcome import SourceAcquisitionOutcome
from forex_agent.domain.timestamps import UtcTimestamp
from tests.fakes.source_operational_observation_repository import (
    FakeSourceOperationalObservationRepository,
)


def _ts(hour: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, hour, tzinfo=UTC))


@pytest.mark.asyncio
async def test_first_observation_is_recorded() -> None:
    repo = FakeSourceOperationalObservationRepository()
    record = RecordSourceOperationalObservation(repo)

    result = await record(
        source_key="FED",
        source_channel="press_monetary",
        run_id="run-1",
        attempt_number=1,
        outcome=SourceAcquisitionOutcome.SUCCESS,
        availability=_ts(9),
        http_status=200,
    )

    assert result.outcome is SourceOperationalObservationOutcome.RECORDED
    assert len(repo.observations) == 1


@pytest.mark.asyncio
async def test_duplicate_delivery_of_the_same_event_is_idempotent() -> None:
    repo = FakeSourceOperationalObservationRepository()
    record = RecordSourceOperationalObservation(repo)

    async def _record_once() -> SourceOperationalObservationOutcome:
        result = await record(
            source_key="FED",
            source_channel="press_monetary",
            run_id="run-1",
            attempt_number=1,
            outcome=SourceAcquisitionOutcome.HTTP_FAILURE,
            availability=_ts(9),
            http_status=503,
        )
        return result.outcome

    first = await _record_once()
    second = await _record_once()

    assert first is SourceOperationalObservationOutcome.RECORDED
    assert second is SourceOperationalObservationOutcome.DUPLICATE
    assert len(repo.observations) == 1


@pytest.mark.asyncio
async def test_distinct_attempt_numbers_within_one_run_are_separate_events() -> None:
    repo = FakeSourceOperationalObservationRepository()
    record = RecordSourceOperationalObservation(repo)

    await record(
        source_key="FED",
        source_channel="press_monetary",
        run_id="run-1",
        attempt_number=1,
        outcome=SourceAcquisitionOutcome.HTTP_FAILURE,
        availability=_ts(9),
        http_status=503,
    )
    await record(
        source_key="FED",
        source_channel="press_monetary",
        run_id="run-1",
        attempt_number=2,
        outcome=SourceAcquisitionOutcome.SUCCESS,
        availability=_ts(9),
        http_status=200,
    )

    assert len(repo.observations) == 2


@pytest.mark.asyncio
async def test_same_attempt_number_different_run_id_are_separate_events() -> None:
    repo = FakeSourceOperationalObservationRepository()
    record = RecordSourceOperationalObservation(repo)

    await record(
        source_key="FED",
        source_channel="press_monetary",
        run_id="run-1",
        attempt_number=1,
        outcome=SourceAcquisitionOutcome.SUCCESS,
        availability=_ts(9),
        http_status=200,
    )
    await record(
        source_key="FED",
        source_channel="press_monetary",
        run_id="run-2",
        attempt_number=1,
        outcome=SourceAcquisitionOutcome.SUCCESS,
        availability=_ts(10),
        http_status=200,
    )

    assert len(repo.observations) == 2


@pytest.mark.asyncio
async def test_default_policy_version_is_fx63_v1() -> None:
    repo = FakeSourceOperationalObservationRepository()
    record = RecordSourceOperationalObservation(repo)

    result = await record(
        source_key="FED",
        source_channel="press_monetary",
        run_id="run-1",
        attempt_number=1,
        outcome=SourceAcquisitionOutcome.SUCCESS,
        availability=_ts(9),
        http_status=200,
    )

    assert result.observation.policy_version == "fx63_v1"
