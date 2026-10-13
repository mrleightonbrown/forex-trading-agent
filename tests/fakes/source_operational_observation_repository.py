"""FX-63: an in-memory fake implementing `SourceOperationalObservation
Repository`, mirroring the real `SqlAlchemySourceOperationalObservation
Repository`'s own idempotent-insert-on-natural-key semantics."""

from forex_agent.application.ports.source_operational_observation_repository import (
    SourceOperationalObservationWriteResult,
)
from forex_agent.domain.source_operational_observation import SourceOperationalObservation
from forex_agent.domain.timestamps import UtcTimestamp


class FakeSourceOperationalObservationRepository:
    def __init__(self) -> None:
        self.observations: dict[tuple[str, str, int], SourceOperationalObservation] = {}

    async def add_observation(
        self, observation: SourceOperationalObservation
    ) -> SourceOperationalObservationWriteResult:
        key = (observation.source_key, observation.run_id, observation.attempt_number)
        if key in self.observations:
            return SourceOperationalObservationWriteResult(inserted=False)
        self.observations[key] = observation
        return SourceOperationalObservationWriteResult(inserted=True)

    async def list_observations_for_source_as_of(
        self, source_key: str, window_start: UtcTimestamp, as_of: UtcTimestamp
    ) -> tuple[SourceOperationalObservation, ...]:
        return tuple(
            o
            for o in self.observations.values()
            if o.source_key == source_key
            and window_start.value <= o.availability.value <= as_of.value
        )

    async def earliest_observation_availability_for_source(
        self, source_key: str, as_of: UtcTimestamp
    ) -> UtcTimestamp | None:
        candidates = [
            o.availability
            for o in self.observations.values()
            if o.source_key == source_key and o.availability.value <= as_of.value
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda ts: ts.value)
