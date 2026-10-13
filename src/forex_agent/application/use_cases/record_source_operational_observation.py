"""FX-63: append-only recording of ONE acquisition-attempt observation
-- deliberately the SIMPLEST recording use case in this codebase: no
PIT ordering check (observations are independent events, not a
"latest wins" vintage sequence) and no determinism check (two
genuinely distinct attempts are never compared against each other --
there is no "same basis" concept here at all). The only invariant is
idempotency on the natural key `(source_key, run_id, attempt_number)`,
enforced by the repository itself (Section 6)."""

from dataclasses import dataclass
from enum import Enum

from forex_agent.application.ports.source_operational_observation_repository import (
    SourceOperationalObservationRepository,
)
from forex_agent.domain.source_acquisition_outcome import SourceAcquisitionOutcome
from forex_agent.domain.source_operational_observation import SourceOperationalObservation
from forex_agent.domain.source_operational_observation_kind import SourceOperationalObservationKind
from forex_agent.domain.timestamps import UtcTimestamp


class SourceOperationalObservationOutcome(Enum):
    RECORDED = "RECORDED"
    DUPLICATE = "DUPLICATE"


@dataclass(frozen=True, slots=True)
class SourceOperationalObservationRecordResult:
    outcome: SourceOperationalObservationOutcome
    observation: SourceOperationalObservation


class RecordSourceOperationalObservation:
    """See the module docstring."""

    def __init__(self, repository: SourceOperationalObservationRepository) -> None:
        self._repository = repository

    async def __call__(
        self,
        source_key: str,
        source_channel: str,
        run_id: str,
        attempt_number: int,
        outcome: SourceAcquisitionOutcome,
        availability: UtcTimestamp,
        http_status: int | None,
        *,
        policy_version: str = "fx63_v1",
        kind: SourceOperationalObservationKind = (
            SourceOperationalObservationKind.ACQUISITION_ATTEMPT
        ),
    ) -> SourceOperationalObservationRecordResult:
        observation = SourceOperationalObservation(
            source_key=source_key,
            source_channel=source_channel,
            run_id=run_id,
            attempt_number=attempt_number,
            kind=kind,
            outcome=outcome,
            availability=availability,
            http_status=http_status,
            policy_version=policy_version,
        )
        write_result = await self._repository.add_observation(observation)
        record_outcome = (
            SourceOperationalObservationOutcome.RECORDED
            if write_result.inserted
            else SourceOperationalObservationOutcome.DUPLICATE
        )
        return SourceOperationalObservationRecordResult(record_outcome, observation)
