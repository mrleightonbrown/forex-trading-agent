"""FX-58H Section 19/20/21: concurrent-write safety through the
`RecordNewsCanonicalRelation`/`CanonicalizeNewsOnce` USE CASES
themselves -- not merely the repository's own `add_relation_vintage`
in isolation (already covered by `test_news_canonicalization_
repository.py::test_concurrent_identical_relation_creation_is_safe`).
This closes the gap FX-58 itself left: the use-case layer's own
CREATED/UNCHANGED reporting under a real race (the Section 18 bug
this story fixes) was previously untested against a genuine two-
session Postgres race.

Requires a live Postgres with migration `3fe8c43841ee` applied (the
current head).
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.application.ports.news_canonicalization_repository import (
    NewsCanonicalRelationConflictError,
)
from forex_agent.application.use_cases.canonicalize_news_once import CanonicalizeNewsOnce
from forex_agent.application.use_cases.record_news_canonical_relation import (
    NewsCanonicalRelationOutcome,
    RecordNewsCanonicalRelation,
)
from forex_agent.domain.news_canonical_relation_kind import NewsCanonicalRelationKind
from forex_agent.domain.news_canonicalization_method import NewsCanonicalizationMethod
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
from forex_agent.infrastructure.db.news_canonicalization_repository import (
    SqlAlchemyNewsCanonicalizationRepository,
)
from forex_agent.infrastructure.db.news_repository import SqlAlchemyNewsRepository
from forex_agent.infrastructure.db.session import get_engine

TEST_SOURCE_KEY = "__fx58h_concurrency_test__"


def _ts(hour: int, minute: int = 0) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, hour, minute, tzinfo=UTC))


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


async def _make_item(
    news_repo: SqlAlchemyNewsRepository,
    suffix: str,
    *,
    canonical_url: str | None = None,
    body_text: str | None = None,
) -> str:
    registration = await news_repo._register_source_item_for_test_setup(
        _identity(suffix), _ts(9), NewsObservationMode.PROSPECTIVE
    )
    vintage = NewsItemVintage(
        news_item_key=registration.news_item_key,
        revision_sequence=0,
        availability=_ts(9),
        observation_mode=NewsObservationMode.PROSPECTIVE,
        headline="H",
        source_channel="test_channel",
        observed_source_channels=("test_channel",),
        source_status=NewsSourceStatus.ACTIVE,
        evidence_disposition=NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
        canonical_url=canonical_url,
        body_text=body_text,
    )
    await news_repo.add_vintage(vintage)
    return registration.news_item_key


# --- Section 20: identical concurrent FIRST creation, through the use case -


@pytest.mark.asyncio
async def test_concurrent_identical_first_creation_one_created_one_unchanged(
    news_repo: SqlAlchemyNewsRepository,
) -> None:
    a = await _make_item(news_repo, "ident-a")
    b = await _make_item(news_repo, "ident-b")

    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)

    async def _record() -> NewsCanonicalRelationOutcome:
        async with session_factory() as own_session:
            own_news_repo = SqlAlchemyNewsRepository(own_session)
            own_canon_repo = SqlAlchemyNewsCanonicalizationRepository(own_session, own_news_repo)
            record = RecordNewsCanonicalRelation(own_canon_repo)
            result = await record(
                (a, 0),
                (b, 0),
                availability=_ts(10),
                relation_kind=NewsCanonicalRelationKind.SAME_STORY,
                method=NewsCanonicalizationMethod.EXACT_CANONICAL_URL,
                algorithm_version="fx58_v2",
            )
            return result.outcome

    outcomes = await asyncio.gather(_record(), _record())
    assert sorted(o.value for o in outcomes) == sorted(
        [NewsCanonicalRelationOutcome.CREATED.value, NewsCanonicalRelationOutcome.UNCHANGED.value]
    )

    async with session_factory() as check_session:
        check_news_repo = SqlAlchemyNewsRepository(check_session)
        check_canon_repo = SqlAlchemyNewsCanonicalizationRepository(check_session, check_news_repo)
        stored = await check_canon_repo.list_relation_vintages_for_pair(*sorted((a, b)))
        assert len(stored) == 1


# --- Section 19: concurrent DIFFERENT payloads for revision 0 --------------


@pytest.mark.asyncio
async def test_concurrent_different_payloads_one_wins_one_raises(
    news_repo: SqlAlchemyNewsRepository,
) -> None:
    a = await _make_item(news_repo, "diff-a")
    b = await _make_item(news_repo, "diff-b")

    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)

    async def _record(method: NewsCanonicalizationMethod) -> str:
        async with session_factory() as own_session:
            own_news_repo = SqlAlchemyNewsRepository(own_session)
            own_canon_repo = SqlAlchemyNewsCanonicalizationRepository(own_session, own_news_repo)
            record = RecordNewsCanonicalRelation(own_canon_repo)
            try:
                result = await record(
                    (a, 0),
                    (b, 0),
                    availability=_ts(10),
                    relation_kind=NewsCanonicalRelationKind.SAME_STORY,
                    method=method,
                    algorithm_version="fx58_v2",
                )
                return result.outcome.value
            except NewsCanonicalRelationConflictError:
                return "CONFLICT"

    results = await asyncio.gather(
        _record(NewsCanonicalizationMethod.EXACT_CANONICAL_URL),
        _record(NewsCanonicalizationMethod.EXACT_BODY_TEXT),
    )

    # Exactly one side wins (CREATED); the other raises a conflict --
    # no silent winner selection, no second revision manufactured.
    assert sorted(results) == sorted([NewsCanonicalRelationOutcome.CREATED.value, "CONFLICT"])

    async with session_factory() as check_session:
        check_news_repo = SqlAlchemyNewsRepository(check_session)
        check_canon_repo = SqlAlchemyNewsCanonicalizationRepository(check_session, check_news_repo)
        stored = await check_canon_repo.list_relation_vintages_for_pair(*sorted((a, b)))
        assert len(stored) == 1


# --- Section 21: CanonicalizeNewsOnce's own counters under a real race -----


@pytest.mark.asyncio
async def test_canonicalizer_relations_created_reflects_actual_durable_creation(
    news_repo: SqlAlchemyNewsRepository,
) -> None:
    a = await _make_item(news_repo, "run-a", canonical_url="https://x.com/concurrent")
    b = await _make_item(news_repo, "run-b", canonical_url="https://x.com/concurrent")

    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)

    async def _run() -> int:
        async with session_factory() as own_session:
            own_news_repo = SqlAlchemyNewsRepository(own_session)
            own_canon_repo = SqlAlchemyNewsCanonicalizationRepository(own_session, own_news_repo)
            record = RecordNewsCanonicalRelation(own_canon_repo)
            canonicalize = CanonicalizeNewsOnce(own_canon_repo, record, clock=lambda: _ts(11))
            result = await canonicalize()
            return result.relations_created

    created_counts = await asyncio.gather(_run(), _run())

    # Exactly one of the two concurrent full runs may durably report
    # having created the relation; the other must report 0 (not
    # fabricate a second revision to "catch up").
    assert sorted(created_counts) == [0, 1]

    async with session_factory() as check_session:
        check_news_repo = SqlAlchemyNewsRepository(check_session)
        check_canon_repo = SqlAlchemyNewsCanonicalizationRepository(check_session, check_news_repo)
        stored = await check_canon_repo.list_relation_vintages_for_pair(*sorted((a, b)))
        assert len(stored) == 1
