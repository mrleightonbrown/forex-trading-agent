"""SQLAlchemy implementation of `MacroObservationRepository` (FX-41;
hardened FX-41H, FX-43H, FX-43H.1, FX-44).

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
from forex_agent.domain.release_timing_rule import ReleaseTimingConfidence
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
        released_at: UtcTimestamp,
        effective_at: UtcTimestamp | None,
        confidence: ReleaseTimingConfidence,
    ) -> None:
        # The ONE UPDATE in this class -- see the class docstring and the
        # port's own docstring for why this is safe: value/revision_sequence
        # are never touched. FX-43H.1/FX-44: this is a single atomic
        # conditional UPDATE, not a SELECT-then-UPDATE -- both outcome flags
        # being False is part of the UPDATE's own WHERE clause, so the
        # still-fully-provisional check and the write happen in one
        # statement, and `RETURNING id` is how we learn whether it actually
        # applied.
        #
        # Under Postgres's default READ COMMITTED isolation this is race-
        # safe: if two sessions race this same UPDATE against the same
        # identity, the second to reach the row blocks on the first's row
        # lock, then -- once the first commits -- re-evaluates its own
        # WHERE clause against the now-committed (already classified) row
        # and correctly matches zero rows, rather than blindly overwriting.
        is_exact = confidence is ReleaseTimingConfidence.EXACT
        stmt = (
            update(MacroObservationVintageRow)
            .where(
                MacroObservationVintageRow.series_key == series_key,
                MacroObservationVintageRow.observation_period == observation_period.value,
                MacroObservationVintageRow.revision_sequence == revision_sequence,
                MacroObservationVintageRow.released_at_is_verified.is_(False),
                MacroObservationVintageRow.released_at_is_conservative_bound.is_(False),
            )
            .values(
                released_at=released_at.value,
                effective_at=(None if effective_at is None else effective_at.value),
                released_at_is_verified=is_exact,
                released_at_is_conservative_bound=not is_exact,
            )
            .returning(MacroObservationVintageRow.id)
        )
        updated_id = (await self._session.execute(stmt)).scalar_one_or_none()
        await self._session.commit()
        if updated_id is not None:
            return

        # The UPDATE above matched zero rows -- it, not this lookup,
        # already decided nothing was written. Everything from here down is
        # diagnostic only: it exists solely to tell "identity doesn't
        # exist" apart from "identity exists but is already classified" in
        # the raised error, and cannot itself cause (or prevent) a write.
        # `_select_one` itself raises the missing-identity error if the row
        # doesn't exist at all; reaching the line below means it exists and
        # -- since the UPDATE's own WHERE already ruled out both flags
        # False -- already has one of the two outcome flags set.
        existing_row = await self._select_one(series_key, observation_period, revision_sequence)
        await self._session.commit()
        existing_classification = (
            "released_at_is_verified=True"
            if existing_row.released_at_is_verified
            else "released_at_is_conservative_bound=True"
        )
        raise ValueError(
            f"vintage identity (series_key={series_key!r}, "
            f"observation_period={observation_period.value.isoformat()!r}, "
            f"revision_sequence={revision_sequence}) is already "
            f"{existing_classification} -- refusing to replace an already-classified "
            "release timing"
        )

    async def list_all_for_series(self, series_key: str) -> tuple[MacroObservationVintage, ...]:
        stmt = select(MacroObservationVintageRow).where(
            MacroObservationVintageRow.series_key == series_key
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        await self._session.commit()  # read-only -- closes out the transaction
        return tuple(_to_domain(row) for row in rows)

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
        released_at_is_conservative_bound=row.released_at_is_conservative_bound,
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
        "released_at_is_conservative_bound": vintage.released_at_is_conservative_bound,
    }
