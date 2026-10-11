"""SQLAlchemy implementation of `NewsCanonicalizationRepository`
(FX-58).

`list_candidates_as_of` reuses `NewsRepository.latest_evidence_
eligible_vintage_as_of` DIRECTLY for the per-item PIT-eligibility
decision (Section 27) -- never a second interpretation of "latest
eligible" written independently here. Every other read/write in this
module follows the exact same idempotent `INSERT ... ON CONFLICT DO
NOTHING ... RETURNING id` discipline `SqlAlchemyNewsRepository`
already established -- no method here ever issues an `UPDATE`
against a relation row (FX-58 Section 50).
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from forex_agent.application.ports.news_canonicalization_repository import (
    NewsCanonicalRelationConflictError,
    RelationVintageWriteResult,
)
from forex_agent.application.ports.news_repository import NewsRepository
from forex_agent.domain.news_canonical_relation_kind import NewsCanonicalRelationKind
from forex_agent.domain.news_canonical_relation_vintage import NewsCanonicalRelationVintage
from forex_agent.domain.news_canonicalization_matching import CanonicalizationCandidate
from forex_agent.domain.news_canonicalization_method import NewsCanonicalizationMethod
from forex_agent.domain.news_item import NewsItem
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.models.news_canonical_relation_vintage import (
    NewsCanonicalRelationVintageRow,
)
from forex_agent.infrastructure.db.models.news_item import NewsItemRow

_RELATION_KEY = ("left_news_item_key", "right_news_item_key", "revision_sequence")


class SqlAlchemyNewsCanonicalizationRepository:
    """Implements `NewsCanonicalizationRepository`."""

    def __init__(self, session: AsyncSession, news_repository: NewsRepository) -> None:
        self._session = session
        self._news_repository = news_repository

    # --- Candidates / items ---------------------------------------------

    async def list_candidates_as_of(
        self, as_of: UtcTimestamp, *, include_backfill: bool = False
    ) -> tuple[CanonicalizationCandidate, ...]:
        rows = (await self._session.execute(select(NewsItemRow))).scalars().all()
        await self._session.commit()

        candidates: list[CanonicalizationCandidate] = []
        for row in rows:
            vintage = await self._news_repository.latest_evidence_eligible_vintage_as_of(
                row.news_item_key, as_of, include_backfill=include_backfill
            )
            if vintage is None:
                continue
            candidates.append(
                CanonicalizationCandidate(
                    news_item_key=row.news_item_key,
                    first_seen_at=UtcTimestamp(row.first_seen_at),
                    revision_sequence=vintage.revision_sequence,
                    availability=vintage.availability,
                    headline=vintage.headline,
                    summary=vintage.summary,
                    body_text=vintage.body_text,
                    canonical_url=vintage.canonical_url,
                )
            )
        return tuple(candidates)

    async def list_items_seen_as_of(self, as_of: UtcTimestamp) -> tuple[NewsItem, ...]:
        stmt = select(NewsItemRow).where(NewsItemRow.first_seen_at <= as_of.value)
        rows = (await self._session.execute(stmt)).scalars().all()
        await self._session.commit()
        return tuple(_item_row_to_domain(row) for row in rows)

    # --- Relations --------------------------------------------------------

    async def latest_relation_for_pair(
        self, left_news_item_key: str, right_news_item_key: str
    ) -> NewsCanonicalRelationVintage | None:
        stmt = (
            select(NewsCanonicalRelationVintageRow)
            .where(
                NewsCanonicalRelationVintageRow.left_news_item_key == left_news_item_key,
                NewsCanonicalRelationVintageRow.right_news_item_key == right_news_item_key,
            )
            .order_by(
                NewsCanonicalRelationVintageRow.availability.desc(),
                NewsCanonicalRelationVintageRow.revision_sequence.desc(),
            )
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        await self._session.commit()
        return None if row is None else _relation_row_to_domain(row)

    async def latest_relation_as_of(
        self, left_news_item_key: str, right_news_item_key: str, as_of: UtcTimestamp
    ) -> NewsCanonicalRelationVintage | None:
        stmt = (
            select(NewsCanonicalRelationVintageRow)
            .where(
                NewsCanonicalRelationVintageRow.left_news_item_key == left_news_item_key,
                NewsCanonicalRelationVintageRow.right_news_item_key == right_news_item_key,
                NewsCanonicalRelationVintageRow.availability <= as_of.value,
            )
            .order_by(
                NewsCanonicalRelationVintageRow.availability.desc(),
                NewsCanonicalRelationVintageRow.revision_sequence.desc(),
            )
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        await self._session.commit()
        return None if row is None else _relation_row_to_domain(row)

    async def list_relation_vintages_for_pair(
        self, left_news_item_key: str, right_news_item_key: str
    ) -> tuple[NewsCanonicalRelationVintage, ...]:
        stmt = select(NewsCanonicalRelationVintageRow).where(
            NewsCanonicalRelationVintageRow.left_news_item_key == left_news_item_key,
            NewsCanonicalRelationVintageRow.right_news_item_key == right_news_item_key,
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        await self._session.commit()
        return tuple(_relation_row_to_domain(row) for row in rows)

    async def list_latest_relation_states_as_of(
        self, as_of: UtcTimestamp
    ) -> tuple[NewsCanonicalRelationVintage, ...]:
        stmt = select(NewsCanonicalRelationVintageRow).where(
            NewsCanonicalRelationVintageRow.availability <= as_of.value
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        await self._session.commit()

        latest_by_pair: dict[tuple[str, str], NewsCanonicalRelationVintageRow] = {}
        for row in rows:
            pair_key = (row.left_news_item_key, row.right_news_item_key)
            current = latest_by_pair.get(pair_key)
            candidate_sort_key = (row.availability, row.revision_sequence)
            if current is None or candidate_sort_key > (
                current.availability,
                current.revision_sequence,
            ):
                latest_by_pair[pair_key] = row
        return tuple(_relation_row_to_domain(row) for row in latest_by_pair.values())

    async def add_relation_vintage(
        self, vintage: NewsCanonicalRelationVintage
    ) -> RelationVintageWriteResult:
        stmt = (
            pg_insert(NewsCanonicalRelationVintageRow)
            .values(_relation_row_values(vintage))
            .on_conflict_do_nothing(index_elements=_RELATION_KEY)
            .returning(NewsCanonicalRelationVintageRow.id)
        )
        inserted_id = (await self._session.execute(stmt)).scalar_one_or_none()
        if inserted_id is not None:
            await self._session.commit()
            return RelationVintageWriteResult(inserted=True)

        existing_row = await self._select_one_relation(
            vintage.left_news_item_key, vintage.right_news_item_key, vintage.revision_sequence
        )
        await self._session.commit()
        assert existing_row is not None  # the failed insert proves the identity already exists
        existing = _relation_row_to_domain(existing_row)
        if existing == vintage:
            return RelationVintageWriteResult(inserted=False)
        raise NewsCanonicalRelationConflictError(existing, vintage)

    async def _select_one_relation(
        self, left_news_item_key: str, right_news_item_key: str, revision_sequence: int
    ) -> NewsCanonicalRelationVintageRow | None:
        stmt = select(NewsCanonicalRelationVintageRow).where(
            NewsCanonicalRelationVintageRow.left_news_item_key == left_news_item_key,
            NewsCanonicalRelationVintageRow.right_news_item_key == right_news_item_key,
            NewsCanonicalRelationVintageRow.revision_sequence == revision_sequence,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()


# --- Domain <-> row mapping -----------------------------------------------


def _item_row_to_domain(row: NewsItemRow) -> NewsItem:
    return NewsItem(
        news_item_key=row.news_item_key,
        first_seen_at=UtcTimestamp(row.first_seen_at),
        first_observation_mode=NewsObservationMode(row.first_observation_mode),
    )


def _relation_row_values(vintage: NewsCanonicalRelationVintage) -> dict[str, Any]:
    return {
        "left_news_item_key": vintage.left_news_item_key,
        "right_news_item_key": vintage.right_news_item_key,
        "revision_sequence": vintage.revision_sequence,
        "availability": vintage.availability.value,
        "relation_kind": vintage.relation_kind.value,
        "method": vintage.method.value,
        "left_item_revision_sequence": vintage.left_item_revision_sequence,
        "right_item_revision_sequence": vintage.right_item_revision_sequence,
        "algorithm_version": vintage.algorithm_version,
    }


def _relation_row_to_domain(row: NewsCanonicalRelationVintageRow) -> NewsCanonicalRelationVintage:
    return NewsCanonicalRelationVintage(
        left_news_item_key=row.left_news_item_key,
        right_news_item_key=row.right_news_item_key,
        revision_sequence=row.revision_sequence,
        availability=UtcTimestamp(row.availability),
        relation_kind=NewsCanonicalRelationKind(row.relation_kind),
        method=NewsCanonicalizationMethod(row.method),
        left_item_revision_sequence=row.left_item_revision_sequence,
        right_item_revision_sequence=row.right_item_revision_sequence,
        algorithm_version=row.algorithm_version,
    )
