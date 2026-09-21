"""SQLAlchemy implementation of `MacroObservationRepository` (FX-41;
hardened FX-41H).

Enforces the point-in-time invariant ("a query at T cannot return a
vintage whose released_at is after T") entirely through the `WHERE
released_at <= :as_of` clause shared by both read methods below --
there is deliberately no separate "safety check" layered on top; the
SQL predicate IS the safety guarantee. `revision_sequence DESC` is a
deterministic tie-breaker appended after `released_at DESC` in both
methods' ordering, so which vintage is returned never depends on scan
order when two vintages share a `released_at`.
"""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from forex_agent.application.ports.macro_observation_repository import (
    MacroVintageConflictError,
)
from forex_agent.domain.macro_observation_vintage import MacroObservationVintage
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.models.macro_observation_vintage import (
    MacroObservationVintageRow,
)

_CONFLICT_KEY = ("series_key", "observation_period", "revision_sequence")


class SqlAlchemyMacroObservationRepository:
    """Implements `MacroObservationRepository`. Every write is a plain
    `INSERT ... ON CONFLICT DO NOTHING` -- there is no UPDATE anywhere
    in this class, so a historical vintage row can never be mutated
    once stored; a revision is always a new row."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_vintage(self, vintage: MacroObservationVintage) -> None:
        stmt = (
            pg_insert(MacroObservationVintageRow)
            .values(_row_values(vintage))
            .on_conflict_do_nothing(index_elements=_CONFLICT_KEY)
            .returning(MacroObservationVintageRow.id)
        )
        inserted_id = (await self._session.execute(stmt)).scalar_one_or_none()
        if inserted_id is not None:
            await self._session.commit()
            return

        # Identity already exists (FX-41H) -- fetch the stored row to decide
        # whether this is an idempotent exact retry or a genuine conflict.
        # Nothing above wrote anything, so this commit only closes out the
        # read-only transaction the failed insert opened.
        existing_row = (
            await self._session.execute(
                select(MacroObservationVintageRow).where(
                    MacroObservationVintageRow.series_key == vintage.series_key,
                    MacroObservationVintageRow.observation_period
                    == vintage.observation_period.value,
                    MacroObservationVintageRow.revision_sequence == vintage.revision_sequence,
                )
            )
        ).scalar_one()
        await self._session.commit()

        existing_vintage = _to_domain(existing_row)
        if existing_vintage == vintage:
            return  # exact retry -- idempotent, not an error
        raise MacroVintageConflictError(existing_vintage, vintage)

    async def latest_available_as_of(
        self, series_key: str, as_of: UtcTimestamp
    ) -> MacroObservationVintage | None:
        stmt = (
            select(MacroObservationVintageRow)
            .where(
                MacroObservationVintageRow.series_key == series_key,
                MacroObservationVintageRow.released_at <= as_of.value,
            )
            .order_by(
                MacroObservationVintageRow.observation_period.desc(),
                MacroObservationVintageRow.released_at.desc(),
                MacroObservationVintageRow.revision_sequence.desc(),
            )
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _to_domain(row)

    async def observation_as_known_at(
        self, series_key: str, observation_period: UtcTimestamp, as_of: UtcTimestamp
    ) -> MacroObservationVintage | None:
        stmt = (
            select(MacroObservationVintageRow)
            .where(
                MacroObservationVintageRow.series_key == series_key,
                MacroObservationVintageRow.observation_period == observation_period.value,
                MacroObservationVintageRow.released_at <= as_of.value,
            )
            .order_by(
                MacroObservationVintageRow.released_at.desc(),
                MacroObservationVintageRow.revision_sequence.desc(),
            )
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _to_domain(row)


def _to_domain(row: MacroObservationVintageRow) -> MacroObservationVintage:
    return MacroObservationVintage(
        series_key=row.series_key,
        observation_period=UtcTimestamp(row.observation_period),
        value=row.value,
        released_at=UtcTimestamp(row.released_at),
        revision_sequence=row.revision_sequence,
        source=row.source,
        effective_at=None if row.effective_at is None else UtcTimestamp(row.effective_at),
    )


def _row_values(vintage: MacroObservationVintage) -> dict[str, object]:
    return {
        "series_key": vintage.series_key,
        "observation_period": vintage.observation_period.value,
        "value": vintage.value,
        "released_at": vintage.released_at.value,
        "effective_at": None if vintage.effective_at is None else vintage.effective_at.value,
        "revision_sequence": vintage.revision_sequence,
        "source": vintage.source,
    }
