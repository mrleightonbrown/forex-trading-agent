"""SQLAlchemy implementation of `SourceOperationalObservationRepository`
(FX-63). Simpler than every FX-56/58/59/62 vintage repository: there is
no revision/correction/determinism concept here at all -- a duplicate
delivery of the SAME `(source_key, run_id, attempt_number)` is always
treated as an idempotent no-op, never compared for content equality
(see that port's own docstring for why)."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from forex_agent.application.ports.source_operational_observation_repository import (
    SourceOperationalObservationWriteResult,
)
from forex_agent.domain.source_acquisition_outcome import SourceAcquisitionOutcome
from forex_agent.domain.source_operational_observation import SourceOperationalObservation
from forex_agent.domain.source_operational_observation_kind import SourceOperationalObservationKind
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.models.source_operational_observation import (
    SourceOperationalObservationRow,
)

_NATURAL_KEY = ("source_key", "run_id", "attempt_number")


class MalformedSourceOperationalObservationRowError(Exception):
    """Raised if a stored row's `kind`/`outcome` string does not match
    any known enum member -- a data-integrity defect, never silently
    coerced to a default."""

    def __init__(self, field: str, value: str) -> None:
        self.field = field
        self.value = value
        super().__init__(f"stored source_operational_observations.{field}={value!r} is unknown")


class SqlAlchemySourceOperationalObservationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_observation(
        self, observation: SourceOperationalObservation
    ) -> SourceOperationalObservationWriteResult:
        stmt = (
            pg_insert(SourceOperationalObservationRow)
            .values(_row_values(observation))
            .on_conflict_do_nothing(index_elements=list(_NATURAL_KEY))
            .returning(SourceOperationalObservationRow.id)
        )
        inserted_id = (await self._session.execute(stmt)).scalar_one_or_none()
        await self._session.commit()
        return SourceOperationalObservationWriteResult(inserted=inserted_id is not None)

    async def list_observations_for_source_as_of(
        self, source_key: str, window_start: UtcTimestamp, as_of: UtcTimestamp
    ) -> tuple[SourceOperationalObservation, ...]:
        stmt = select(SourceOperationalObservationRow).where(
            SourceOperationalObservationRow.source_key == source_key,
            SourceOperationalObservationRow.availability >= window_start.value,
            SourceOperationalObservationRow.availability <= as_of.value,
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        await self._session.commit()
        return tuple(_row_to_domain(row) for row in rows)


def _row_values(observation: SourceOperationalObservation) -> dict[str, object]:
    return {
        "source_key": observation.source_key,
        "source_channel": observation.source_channel,
        "run_id": observation.run_id,
        "attempt_number": observation.attempt_number,
        "kind": observation.kind.value,
        "outcome": observation.outcome.value,
        "availability": observation.availability.value,
        "http_status": observation.http_status,
        "policy_version": observation.policy_version,
    }


def _row_to_domain(row: SourceOperationalObservationRow) -> SourceOperationalObservation:
    try:
        kind = SourceOperationalObservationKind(row.kind)
    except ValueError as exc:
        raise MalformedSourceOperationalObservationRowError("kind", row.kind) from exc
    try:
        outcome = SourceAcquisitionOutcome(row.outcome)
    except ValueError as exc:
        raise MalformedSourceOperationalObservationRowError("outcome", row.outcome) from exc
    return SourceOperationalObservation(
        source_key=row.source_key,
        source_channel=row.source_channel,
        run_id=row.run_id,
        attempt_number=row.attempt_number,
        kind=kind,
        outcome=outcome,
        availability=UtcTimestamp(row.availability),
        http_status=row.http_status,
        policy_version=row.policy_version,
    )
