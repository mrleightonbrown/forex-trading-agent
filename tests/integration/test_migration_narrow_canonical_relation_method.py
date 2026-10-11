"""FX-58H: proves the CURRENT (post-migration-`3fe8c43841ee`) schema
state against live Postgres -- a real `CHECK` constraint rejection
can only be demonstrated against a real database; the mocked
`alembic.op` logic test (`tests/unit/infrastructure/test_migration_
narrow_canonical_relation_method.py`) covers the precheck/constraint-
swap LOGIC, this file covers the resulting live constraint itself.

Requires a live Postgres with migration `3fe8c43841ee` applied (the
current head) -- run `docker compose up -d db && alembic upgrade
head` first.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.domain.news_evidence_disposition import NewsEvidenceDisposition
from forex_agent.domain.news_item_vintage import NewsItemVintage
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.news_source_identity import NewsSourceIdentity
from forex_agent.domain.news_source_status import NewsSourceStatus
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.models.news_canonical_relation_vintage import (
    NewsCanonicalRelationVintageRow,
)
from forex_agent.infrastructure.db.models.news_item import NewsItemRow
from forex_agent.infrastructure.db.models.news_item_vintage import NewsItemVintageRow
from forex_agent.infrastructure.db.models.news_source_mapping import NewsSourceMappingRow
from forex_agent.infrastructure.db.news_repository import SqlAlchemyNewsRepository
from forex_agent.infrastructure.db.session import get_engine

TEST_SOURCE_KEY = "__fx58h_migration_test__"


def _ts(hour: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, hour, tzinfo=UTC))


def _identity(suffix: str) -> NewsSourceIdentity:
    return NewsSourceIdentity(source_key=TEST_SOURCE_KEY, external_item_id=suffix)


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    async with session_factory() as db_session:
        yield db_session

    async with session_factory() as cleanup_session:
        item_keys = (
            (
                await cleanup_session.execute(
                    delete(NewsSourceMappingRow)
                    .where(NewsSourceMappingRow.source_key == TEST_SOURCE_KEY)
                    .returning(NewsSourceMappingRow.news_item_key)
                )
            )
            .scalars()
            .all()
        )
        for key in item_keys:
            await cleanup_session.execute(
                delete(NewsCanonicalRelationVintageRow).where(
                    (NewsCanonicalRelationVintageRow.left_news_item_key == key)
                    | (NewsCanonicalRelationVintageRow.right_news_item_key == key)
                )
            )
            await cleanup_session.execute(
                delete(NewsItemVintageRow).where(NewsItemVintageRow.news_item_key == key)
            )
            await cleanup_session.execute(
                delete(NewsItemRow).where(NewsItemRow.news_item_key == key)
            )
        await cleanup_session.commit()


@pytest.fixture
def news_repo(session: AsyncSession) -> SqlAlchemyNewsRepository:
    return SqlAlchemyNewsRepository(session)


async def _make_item(news_repo: SqlAlchemyNewsRepository, suffix: str) -> str:
    registration = await news_repo._register_source_item_for_test_setup(
        _identity(suffix), _ts(10), NewsObservationMode.PROSPECTIVE
    )
    vintage = NewsItemVintage(
        news_item_key=registration.news_item_key,
        revision_sequence=0,
        availability=_ts(10),
        observation_mode=NewsObservationMode.PROSPECTIVE,
        headline="H",
        source_channel="test_channel",
        observed_source_channels=("test_channel",),
        source_status=NewsSourceStatus.ACTIVE,
        evidence_disposition=NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
    )
    await news_repo.add_vintage(vintage)
    return registration.news_item_key


@pytest.mark.asyncio
async def test_permitted_v2_methods_still_succeed(
    news_repo: SqlAlchemyNewsRepository, session: AsyncSession
) -> None:
    a = await _make_item(news_repo, "permitted-a")
    b = await _make_item(news_repo, "permitted-b")
    left, right = sorted((a, b))

    for method in ("EXACT_CANONICAL_URL", "EXACT_BODY_TEXT"):
        await session.execute(
            text(
                "INSERT INTO news_canonical_relation_vintages "
                "(left_news_item_key, right_news_item_key, revision_sequence, availability, "
                "relation_kind, method, left_item_revision_sequence, right_item_revision_sequence, "
                "algorithm_version) "
                "VALUES (:left, :right, :rev, now(), 'SAME_STORY', :method, 0, 0, 'fx58_v2')"
            ),
            {
                "left": left,
                "right": right,
                "rev": 0 if method == "EXACT_CANONICAL_URL" else 1,
                "method": method,
            },
        )
    await session.commit()


@pytest.mark.asyncio
async def test_manual_review_method_still_succeeds(
    news_repo: SqlAlchemyNewsRepository, session: AsyncSession
) -> None:
    a = await _make_item(news_repo, "manual-a")
    b = await _make_item(news_repo, "manual-b")
    left, right = sorted((a, b))

    await session.execute(
        text(
            "INSERT INTO news_canonical_relation_vintages "
            "(left_news_item_key, right_news_item_key, revision_sequence, availability, "
            "relation_kind, method, left_item_revision_sequence, right_item_revision_sequence, "
            "algorithm_version) "
            "VALUES (:left, :right, 0, now(), 'NOT_SAME_STORY', 'MANUAL_REVIEW', 0, 0, 'fx58_v2')"
        ),
        {"left": left, "right": right},
    )
    await session.commit()


@pytest.mark.asyncio
async def test_demoted_method_is_rejected_by_the_live_constraint(
    news_repo: SqlAlchemyNewsRepository, session: AsyncSession
) -> None:
    a = await _make_item(news_repo, "rejected-a")
    b = await _make_item(news_repo, "rejected-b")
    left, right = sorted((a, b))

    with pytest.raises(IntegrityError, match="ck_ncrv_method"):
        await session.execute(
            text(
                "INSERT INTO news_canonical_relation_vintages "
                "(left_news_item_key, right_news_item_key, revision_sequence, availability, "
                "relation_kind, method, left_item_revision_sequence, right_item_revision_sequence, "
                "algorithm_version) "
                "VALUES (:left, :right, 0, now(), 'SAME_STORY', 'EXACT_HEADLINE_AND_SUMMARY', "
                "0, 0, 'fx58_v1')"
            ),
            {"left": left, "right": right},
        )
