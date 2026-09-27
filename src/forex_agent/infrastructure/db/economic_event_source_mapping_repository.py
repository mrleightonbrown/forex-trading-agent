"""SQLAlchemy implementation of `EconomicEventSourceMappingRepository`
(FX-52AH).

Same idempotent-write discipline as `SqlAlchemyEconomicEventRepository`
(FX-51): every write is `INSERT ... ON CONFLICT DO NOTHING ...
RETURNING id`, never an UPDATE -- a mapping, once recorded, is
permanent; `record_mapping` never overwrites one, it only detects
whether a conflicting attempt occurred.
"""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from forex_agent.application.ports.economic_event_source_mapping_repository import (
    EconomicEventSourceMappingConflictError,
)
from forex_agent.infrastructure.db.models.economic_event_source_mapping import (
    EconomicEventSourceMappingRow,
)

_MAPPING_KEY = ("source", "external_event_id", "indicator_key")


class SqlAlchemyEconomicEventSourceMappingRepository:
    """Implements `EconomicEventSourceMappingRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_occurrence_key(
        self, source: str, external_event_id: str, indicator_key: str
    ) -> str | None:
        stmt = select(EconomicEventSourceMappingRow.occurrence_key).where(
            EconomicEventSourceMappingRow.source == source,
            EconomicEventSourceMappingRow.external_event_id == external_event_id,
            EconomicEventSourceMappingRow.indicator_key == indicator_key,
        )
        result = (await self._session.execute(stmt)).scalar_one_or_none()
        await self._session.commit()
        return result

    async def record_mapping(
        self, source: str, external_event_id: str, indicator_key: str, occurrence_key: str
    ) -> None:
        stmt = (
            pg_insert(EconomicEventSourceMappingRow)
            .values(
                source=source,
                external_event_id=external_event_id,
                indicator_key=indicator_key,
                occurrence_key=occurrence_key,
            )
            .on_conflict_do_nothing(index_elements=_MAPPING_KEY)
            .returning(EconomicEventSourceMappingRow.id)
        )
        inserted_id = (await self._session.execute(stmt)).scalar_one_or_none()
        if inserted_id is not None:
            await self._session.commit()
            return

        existing = await self.get_occurrence_key(source, external_event_id, indicator_key)
        assert existing is not None  # the failed insert proves the identity already exists
        if existing == occurrence_key:
            return  # idempotent repeat -- not a conflict
        raise EconomicEventSourceMappingConflictError(
            source, external_event_id, indicator_key, existing, occurrence_key
        )
