"""FX-58 Section 60: end-to-end deterministic test exercising the
FULL chain -- `NewsItem`s/`NewsItemVintage`s already in Postgres ->
`SqlAlchemyNewsCanonicalizationRepository.list_candidates_as_of` ->
the pure matcher -> `CanonicalizeNewsOnce` -> `NewsCanonicalRelation
Vintage` -> `GetCanonicalNewsGroupsAsOf` -- proving full PIT behavior
end-to-end, not just at the unit/repository layer in isolation.

Covers the group PIT worked example (Section 38), transitive grouping
(Section 39), the contradictory-graph fail-closed example (Section
40), and the Section 26 anti-overmerge regression re-proven through
the REAL automatic matcher against realistic ECB-shaped fixtures.

Requires a live Postgres with the FX-58 migration (`274aabcc57dd`)
applied -- run `docker compose up -d db && alembic upgrade head`
first. Uses a dedicated test `source_key` prefix (never a real
source).
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.application.use_cases.canonicalize_news_once import CanonicalizeNewsOnce
from forex_agent.application.use_cases.get_canonical_news_groups_as_of import (
    GetCanonicalNewsGroupsAsOf,
)
from forex_agent.application.use_cases.record_news_canonical_relation import (
    RecordNewsCanonicalRelation,
)
from forex_agent.domain.news_canonical_grouping import NewsCanonicalizationInconsistentStateError
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

TEST_SOURCE_KEY = "__fx58_e2e_test__"


def _ts(hour: int, minute: int = 0, second: int = 0) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, hour, minute, second, tzinfo=UTC))


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


@pytest.fixture
def canon_repo(
    session: AsyncSession, news_repo: SqlAlchemyNewsRepository
) -> SqlAlchemyNewsCanonicalizationRepository:
    return SqlAlchemyNewsCanonicalizationRepository(session, news_repo)


async def _make_item(
    news_repo: SqlAlchemyNewsRepository,
    suffix: str,
    *,
    availability: UtcTimestamp,
    headline: str = "H",
    summary: str | None = None,
    body_text: str | None = None,
    canonical_url: str | None = None,
) -> str:
    registration = await news_repo._register_source_item_for_test_setup(
        _identity(suffix), availability, NewsObservationMode.PROSPECTIVE
    )
    vintage = NewsItemVintage(
        news_item_key=registration.news_item_key,
        revision_sequence=0,
        availability=availability,
        observation_mode=NewsObservationMode.PROSPECTIVE,
        headline=headline,
        source_channel="test_channel",
        observed_source_channels=("test_channel",),
        source_status=NewsSourceStatus.ACTIVE,
        evidence_disposition=NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
        summary=summary,
        body_text=body_text,
        canonical_url=canonical_url,
    )
    await news_repo.add_vintage(vintage)
    return registration.news_item_key


# --- Full chain, one genuine SAME_STORY match (Section 60) -----------------


@pytest.mark.asyncio
async def test_full_chain_exact_url_match_creates_relation_and_group(
    news_repo: SqlAlchemyNewsRepository,
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
) -> None:
    a = await _make_item(news_repo, "chain-a", availability=_ts(9), canonical_url="https://x.com/1")
    b = await _make_item(news_repo, "chain-b", availability=_ts(9), canonical_url="https://x.com/1")

    record = RecordNewsCanonicalRelation(canon_repo)
    canonicalize = CanonicalizeNewsOnce(canon_repo, record, clock=lambda: _ts(10))
    result = await canonicalize()

    assert result.relations_created == 1
    relation = await canon_repo.latest_relation_for_pair(*sorted((a, b)))
    assert relation is not None
    assert relation.relation_kind is NewsCanonicalRelationKind.SAME_STORY
    assert relation.method is NewsCanonicalizationMethod.EXACT_CANONICAL_URL

    get_groups = GetCanonicalNewsGroupsAsOf(canon_repo)
    groups = await get_groups(_ts(10, 0, 1))
    matching = [g for g in groups if a in g.member_news_item_keys]
    assert len(matching) == 1
    assert set(matching[0].member_news_item_keys) == {a, b}


# --- Group PIT worked example (Section 38) ----------------------------------


@pytest.mark.asyncio
async def test_group_pit_worked_example(
    news_repo: SqlAlchemyNewsRepository,
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
) -> None:
    # Items A and B both exist by 09:00; the canonicalizer does not
    # discover the duplicate relation until 10:00.
    a = await _make_item(
        news_repo, "group-pit-a", availability=_ts(9), canonical_url="https://x.com/g"
    )
    b = await _make_item(
        news_repo, "group-pit-b", availability=_ts(9), canonical_url="https://x.com/g"
    )

    record = RecordNewsCanonicalRelation(canon_repo)
    canonicalize = CanonicalizeNewsOnce(canon_repo, record, clock=lambda: _ts(10))
    await canonicalize()

    get_groups = GetCanonicalNewsGroupsAsOf(canon_repo)

    groups_at_0930 = await get_groups(_ts(9, 30))
    members_at_0930 = {frozenset(g.member_news_item_keys) for g in groups_at_0930}
    assert frozenset({a}) in members_at_0930
    assert frozenset({b}) in members_at_0930
    assert frozenset({a, b}) not in members_at_0930

    groups_at_1030 = await get_groups(_ts(10, 30))
    members_at_1030 = {frozenset(g.member_news_item_keys) for g in groups_at_1030}
    assert frozenset({a, b}) in members_at_1030


# --- Transitive grouping (Section 39) ---------------------------------------


@pytest.mark.asyncio
async def test_transitive_grouping_a_b_and_b_c(
    news_repo: SqlAlchemyNewsRepository,
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
) -> None:
    a = await _make_item(news_repo, "trans-a", availability=_ts(9))
    b = await _make_item(news_repo, "trans-b", availability=_ts(9, 1))
    c = await _make_item(news_repo, "trans-c", availability=_ts(9, 2))

    record = RecordNewsCanonicalRelation(canon_repo)
    await record(
        (a, 0),
        (b, 0),
        availability=_ts(10),
        relation_kind=NewsCanonicalRelationKind.SAME_STORY,
        method=NewsCanonicalizationMethod.EXACT_CANONICAL_URL,
        algorithm_version="fx58_v2",
    )
    await record(
        (b, 0),
        (c, 0),
        availability=_ts(10),
        relation_kind=NewsCanonicalRelationKind.SAME_STORY,
        method=NewsCanonicalizationMethod.EXACT_CANONICAL_URL,
        algorithm_version="fx58_v2",
    )

    get_groups = GetCanonicalNewsGroupsAsOf(canon_repo)
    groups = await get_groups(_ts(10, 30))
    matching = [g for g in groups if a in g.member_news_item_keys]
    assert len(matching) == 1
    assert set(matching[0].member_news_item_keys) == {a, b, c}
    # Group key is the earliest first_seen member -- "a" was seen first.
    assert matching[0].canonical_group_key == a


# --- Contradictory graph fails closed (Section 40) --------------------------


@pytest.mark.asyncio
async def test_contradictory_graph_fails_closed(
    news_repo: SqlAlchemyNewsRepository,
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
) -> None:
    a = await _make_item(news_repo, "contra-a", availability=_ts(9))
    b = await _make_item(news_repo, "contra-b", availability=_ts(9, 1))
    c = await _make_item(news_repo, "contra-c", availability=_ts(9, 2))

    record = RecordNewsCanonicalRelation(canon_repo)
    await record(
        (a, 0),
        (b, 0),
        availability=_ts(10),
        relation_kind=NewsCanonicalRelationKind.SAME_STORY,
        method=NewsCanonicalizationMethod.EXACT_CANONICAL_URL,
        algorithm_version="fx58_v2",
    )
    await record(
        (b, 0),
        (c, 0),
        availability=_ts(10),
        relation_kind=NewsCanonicalRelationKind.SAME_STORY,
        method=NewsCanonicalizationMethod.EXACT_CANONICAL_URL,
        algorithm_version="fx58_v2",
    )
    await record(
        (a, 0),
        (c, 0),
        availability=_ts(11),
        relation_kind=NewsCanonicalRelationKind.NOT_SAME_STORY,
        method=NewsCanonicalizationMethod.MANUAL_REVIEW,
        algorithm_version="fx58_v2",
    )

    get_groups = GetCanonicalNewsGroupsAsOf(canon_repo)
    with pytest.raises(NewsCanonicalizationInconsistentStateError):
        await get_groups(_ts(11, 30))


# --- Section 26 anti-overmerge regression, through the real matcher --------


@pytest.mark.asyncio
async def test_ecb_decision_and_account_remain_distinct_through_real_matcher(
    news_repo: SqlAlchemyNewsRepository,
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
) -> None:
    decision = await _make_item(
        news_repo,
        "ecb-e2e-decision",
        availability=_ts(9),
        headline="Monetary policy decisions",
        canonical_url="https://www.ecb.europa.eu//press/pr/date/2026/html/ecb.pr260910~x.en.html",
    )
    account = await _make_item(
        news_repo,
        "ecb-e2e-account",
        availability=_ts(9, 1),
        headline="Meeting of 9-10 September 2026",
        canonical_url=(
            "https://www.ecb.europa.eu//press/accounts/2026/html/ecb.mg261008~y.en.html"
        ),
    )
    speech = await _make_item(
        news_repo,
        "ecb-e2e-speech",
        availability=_ts(9, 2),
        headline="Christine Lagarde: press conference introductory statement",
        canonical_url="https://www.ecb.europa.eu//press/key/date/2026/html/ecb.sp260910~z.en.html",
    )

    record = RecordNewsCanonicalRelation(canon_repo)
    canonicalize = CanonicalizeNewsOnce(canon_repo, record, clock=lambda: _ts(10))
    result = await canonicalize()

    assert result.relations_created == 0
    get_groups = GetCanonicalNewsGroupsAsOf(canon_repo)
    groups = await get_groups(_ts(10, 30))
    groups_by_member = {key: g for g in groups for key in g.member_news_item_keys}
    assert groups_by_member[decision].member_news_item_keys == (decision,)
    assert groups_by_member[account].member_news_item_keys == (account,)
    assert groups_by_member[speech].member_news_item_keys == (speech,)


# --- Source data remains untouched (Section 3/63) ---------------------------


@pytest.mark.asyncio
async def test_canonicalization_never_mutates_source_news_items(
    news_repo: SqlAlchemyNewsRepository,
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
    session: AsyncSession,
) -> None:
    a = await _make_item(news_repo, "nomut-a", availability=_ts(9), canonical_url="https://x.com/n")
    b = await _make_item(news_repo, "nomut-b", availability=_ts(9), canonical_url="https://x.com/n")

    vintages_before = await news_repo.list_vintages(a)

    record = RecordNewsCanonicalRelation(canon_repo)
    canonicalize = CanonicalizeNewsOnce(canon_repo, record, clock=lambda: _ts(10))
    await canonicalize()

    vintages_after = await news_repo.list_vintages(a)
    assert vintages_before == vintages_after
    item_a = await news_repo.get_item(a)
    item_b = await news_repo.get_item(b)
    assert item_a is not None
    assert item_b is not None
    assert item_a.first_seen_at == _ts(9)
    assert item_b.first_seen_at == _ts(9)
