"""SQLAlchemy implementation of `MacroObservationRepository` (FX-41;
hardened FX-41H, FX-43H).

Enforces the point-in-time invariant ("a query at T cannot return a
vintage whose released_at is after T") entirely through the `WHERE
released_at <= :as_of` clause shared by both read methods below --
there is deliberately no separate "safety check" layered on top; the
SQL predicate IS the safety guarantee. `revision_sequence DESC` is a
deterministic tie-breaker appended after `released_at DESC` in both
methods' ordering, so which vintage is returned never depends on scan
order when two vintages share a `released_at`.
"""

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from forex_agent.application.ports.macro_observation_repository import (
    MacroVintageConflictError,
    VintageWriteOutcome,
)
from forex_agent.domain.macro_observation_vintage import MacroObservationVintage
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.models.macro_observation_vintage import (
    MacroObservationVintageRow,
)

_CONFLICT_KEY = ("series_key", "observation_period", "revision_sequence")


class SqlAlchemyMacroObservationRepository:
    """Implements `MacroObservationRepository`. Every write except
    `replace_provisional_release_timing` is a plain `INSERT ... ON
    CONFLICT DO NOTHING` -- no other method ever issues an UPDATE, so a
    historical vintage row's ECONOMIC VALUE can never be mutated once
    stored; a revision is always a new row."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_vintage(self, vintage: MacroObservationVintage) -> VintageWriteOutcome:
        stmt = (
            pg_insert(MacroObservationVintageRow)
            .values(_row_values(vintage))
            .on_conflict_do_nothing(index_elements=_CONFLICT_KEY)
            .returning(MacroObservationVintageRow.id)
        )
        inserted_id = (await self._session.execute(stmt)).scalar_one_or_none()
        if inserted_id is not None:
            await self._session.commit()
            return VintageWriteOutcome.INSERTED

        # Identity already exists (FX-41H) -- fetch the stored row to decide
        # whether this is an idempotent exact retry or a genuine conflict.
        # Nothing above wrote anything, so this commit only closes out the
        # read-only transaction the failed insert opened.
        existing_row = await self._select_one(
            vintage.series_key, vintage.observation_period, vintage.revision_sequence
        )
        await self._session.commit()

        existing_vintage = _to_domain(existing_row)
        if existing_vintage == vintage:
            return VintageWriteOutcome.ALREADY_PRESENT  # exact retry -- idempotent, not an error
        raise MacroVintageConflictError(existing_vintage, vintage)

    async def replace_provisional_release_timing(
        self,
        series_key: str,
        observation_period: UtcTimestamp,
        revision_sequence: int,
        verified_released_at: UtcTimestamp,
        verified_effective_at: UtcTimestamp | None,
    ) -> None:
        # The ONE UPDATE in this class -- see the class docstring and the
        # port's own docstring for why this is safe: value/revision_sequence
        # are never touched, and the existing row must already be marked
        # provisional (released_at_is_verified=False) or this refuses.
        existing_row = await self._select_one(series_key, observation_period, revision_sequence)
        if not existing_row.released_at_is_verified:
            stmt = (
                update(MacroObservationVintageRow)
                .where(MacroObservationVintageRow.id == existing_row.id)
                .values(
                    released_at=verified_released_at.value,
                    effective_at=(
                        None if verified_effective_at is None else verified_effective_at.value
                    ),
                    released_at_is_verified=True,
                )
            )
            await self._session.execute(stmt)
            await self._session.commit()
            return

        await self._session.commit()  # close out the read-only lookup above
        raise ValueError(
            f"vintage identity (series_key={series_key!r}, "
            f"observation_period={observation_period.value.isoformat()!r}, "
            f"revision_sequence={revision_sequence}) is already "
            "released_at_is_verified=True -- refusing to replace an already-verified "
            "release timing"
        )

    async def _select_one(
        self, series_key: str, observation_period: UtcTimestamp, revision_sequence: int
    ) -> MacroObservationVintageRow:
        stmt = select(MacroObservationVintageRow).where(
            MacroObservationVintageRow.series_key == series_key,
            MacroObservationVintageRow.observation_period == observation_period.value,
            MacroObservationVintageRow.revision_sequence == revision_sequence,
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            raise ValueError(
                f"no vintage exists at identity (series_key={series_key!r}, "
                f"observation_period={observation_period.value.isoformat()!r}, "
                f"revision_sequence={revision_sequence})"
            )
        return row

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
        released_at_is_verified=row.released_at_is_verified,
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
        "released_at_is_verified": vintage.released_at_is_verified,
    }
