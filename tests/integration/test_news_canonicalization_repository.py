"""FX-58 Section 57: `SqlAlchemyNewsCanonicalizationRepository`
round-trip, point-in-time query, FK, and conflict/idempotency tests
against live Postgres.

Requires a live Postgres with the FX-58 migration (`274aabcc57dd`)
applied -- run `docker compose up -d db && alembic upgrade head`
first. Uses a dedicated test `source_key` prefix (never a real
source), so genuine rows from any real adapter are never at risk.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.application.ports.news_canonicalization_repository import (
    NewsCanonicalRelationConflictError,
)
from forex_agent.domain.news_canonical_relation_kind import NewsCanonicalRelationKind
from forex_agent.domain.news_canonical_relation_vintage import NewsCanonicalRelationVintage
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

TEST_SOURCE_KEY = "__fx58_repo_test__"


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
    evidence_disposition: NewsEvidenceDisposition = NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
    quarantine_reason: str | None = None,
    observation_mode: NewsObservationMode = NewsObservationMode.PROSPECTIVE,
) -> str:
    registration = await news_repo._register_source_item_for_test_setup(
        _identity(suffix), availability, observation_mode
    )
    vintage = NewsItemVintage(
        news_item_key=registration.news_item_key,
        revision_sequence=0,
        availability=availability,
        observation_mode=observation_mode,
        headline=headline,
        source_channel="test_channel",
        observed_source_channels=("test_channel",),
        source_status=NewsSourceStatus.ACTIVE,
        evidence_disposition=evidence_disposition,
        summary=summary,
        body_text=body_text,
        canonical_url=canonical_url,
        quarantine_reason=quarantine_reason,
    )
    await news_repo.add_vintage(vintage)
    return registration.news_item_key


def _relation(
    left: str,
    right: str,
    *,
    revision_sequence: int = 0,
    availability: UtcTimestamp,
    relation_kind: NewsCanonicalRelationKind = NewsCanonicalRelationKind.SAME_STORY,
    method: NewsCanonicalizationMethod = NewsCanonicalizationMethod.EXACT_CANONICAL_URL,
    left_item_revision_sequence: int = 0,
    right_item_revision_sequence: int = 0,
    algorithm_version: str = "fx58_v2",
) -> NewsCanonicalRelationVintage:
    left_key, right_key = sorted((left, right))
    return NewsCanonicalRelationVintage(
        left_news_item_key=left_key,
        right_news_item_key=right_key,
        revision_sequence=revision_sequence,
        availability=availability,
        relation_kind=relation_kind,
        method=method,
        left_item_revision_sequence=left_item_revision_sequence,
        right_item_revision_sequence=right_item_revision_sequence,
        algorithm_version=algorithm_version,
    )


# --- Round-trip / PIT --------------------------------------------------------


async def test_relation_round_trip(
    news_repo: SqlAlchemyNewsRepository,
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
) -> None:
    a = await _make_item(news_repo, "rt-a", availability=_ts(10))
    b = await _make_item(news_repo, "rt-b", availability=_ts(10))
    relation = _relation(a, b, availability=_ts(11))

    await canon_repo.add_relation_vintage(relation)

    stored = await canon_repo.list_relation_vintages_for_pair(
        relation.left_news_item_key, relation.right_news_item_key
    )
    assert stored == (relation,)


async def test_latest_relation_before_first_availability_is_none(
    news_repo: SqlAlchemyNewsRepository,
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
) -> None:
    a = await _make_item(news_repo, "pit-a", availability=_ts(10))
    b = await _make_item(news_repo, "pit-b", availability=_ts(10))
    relation = _relation(a, b, availability=_ts(11))
    await canon_repo.add_relation_vintage(relation)

    before = await canon_repo.latest_relation_as_of(
        relation.left_news_item_key, relation.right_news_item_key, _ts(10, 30)
    )
    assert before is None

    at_or_after = await canon_repo.latest_relation_as_of(
        relation.left_news_item_key, relation.right_news_item_key, _ts(11)
    )
    assert at_or_after == relation


async def test_same_story_visible_after_t1_not_same_story_visible_after_t2(
    news_repo: SqlAlchemyNewsRepository,
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
) -> None:
    a = await _make_item(news_repo, "rev-a", availability=_ts(10))
    b = await _make_item(news_repo, "rev-b", availability=_ts(10))
    left, right = sorted((a, b))

    same = _relation(a, b, revision_sequence=0, availability=_ts(10, 0))
    await canon_repo.add_relation_vintage(same)
    not_same = _relation(
        a,
        b,
        revision_sequence=1,
        availability=_ts(11, 0),
        relation_kind=NewsCanonicalRelationKind.NOT_SAME_STORY,
        method=NewsCanonicalizationMethod.MANUAL_REVIEW,
    )
    await canon_repo.add_relation_vintage(not_same)

    at_1030 = await canon_repo.latest_relation_as_of(left, right, _ts(10, 30))
    assert at_1030 is not None
    assert at_1030.relation_kind is NewsCanonicalRelationKind.SAME_STORY

    at_1130 = await canon_repo.latest_relation_as_of(left, right, _ts(11, 30))
    assert at_1130 is not None
    assert at_1130.relation_kind is NewsCanonicalRelationKind.NOT_SAME_STORY


async def test_equal_availability_higher_revision_wins(
    news_repo: SqlAlchemyNewsRepository,
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
) -> None:
    a = await _make_item(news_repo, "tie-a", availability=_ts(10))
    b = await _make_item(news_repo, "tie-b", availability=_ts(10))
    left, right = sorted((a, b))

    first = _relation(a, b, revision_sequence=0, availability=_ts(12))
    await canon_repo.add_relation_vintage(first)
    second = _relation(
        a,
        b,
        revision_sequence=1,
        availability=_ts(12),  # SAME availability, higher revision
        relation_kind=NewsCanonicalRelationKind.NOT_SAME_STORY,
        method=NewsCanonicalizationMethod.MANUAL_REVIEW,
    )
    await canon_repo.add_relation_vintage(second)

    latest = await canon_repo.latest_relation_as_of(left, right, _ts(12))
    assert latest is not None
    assert latest.revision_sequence == 1
    assert latest.relation_kind is NewsCanonicalRelationKind.NOT_SAME_STORY


# --- FK enforcement ----------------------------------------------------------


async def test_fk_rejects_unknown_news_item(
    news_repo: SqlAlchemyNewsRepository,
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
) -> None:
    a = await _make_item(news_repo, "fk-a", availability=_ts(10))
    bogus_right = f"{a}-does-not-exist"
    left, right = sorted((a, bogus_right))
    relation = NewsCanonicalRelationVintage(
        left_news_item_key=left,
        right_news_item_key=right,
        revision_sequence=0,
        availability=_ts(11),
        relation_kind=NewsCanonicalRelationKind.SAME_STORY,
        method=NewsCanonicalizationMethod.EXACT_CANONICAL_URL,
        left_item_revision_sequence=0,
        right_item_revision_sequence=0,
        algorithm_version="fx58_v2",
    )
    with pytest.raises(IntegrityError):
        await canon_repo.add_relation_vintage(relation)


async def test_fk_rejects_unknown_vintage_revision_sequence(
    news_repo: SqlAlchemyNewsRepository,
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
) -> None:
    a = await _make_item(news_repo, "fk2-a", availability=_ts(10))
    b = await _make_item(news_repo, "fk2-b", availability=_ts(10))
    relation = _relation(
        a,
        b,
        availability=_ts(11),
        left_item_revision_sequence=99,  # never created
    )
    with pytest.raises(IntegrityError):
        await canon_repo.add_relation_vintage(relation)


# --- Idempotency / conflict ---------------------------------------------------


async def test_identical_write_is_idempotent(
    news_repo: SqlAlchemyNewsRepository,
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
) -> None:
    a = await _make_item(news_repo, "idem-a", availability=_ts(10))
    b = await _make_item(news_repo, "idem-b", availability=_ts(10))
    relation = _relation(a, b, availability=_ts(11))

    first = await canon_repo.add_relation_vintage(relation)
    second = await canon_repo.add_relation_vintage(relation)

    assert first.inserted is True
    assert second.inserted is False
    stored = await canon_repo.list_relation_vintages_for_pair(
        relation.left_news_item_key, relation.right_news_item_key
    )
    assert len(stored) == 1


async def test_conflicting_write_raises(
    news_repo: SqlAlchemyNewsRepository,
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
) -> None:
    a = await _make_item(news_repo, "conflict-a", availability=_ts(10))
    b = await _make_item(news_repo, "conflict-b", availability=_ts(10))
    first = _relation(
        a, b, availability=_ts(11), method=NewsCanonicalizationMethod.EXACT_CANONICAL_URL
    )
    await canon_repo.add_relation_vintage(first)

    conflicting = _relation(
        a, b, availability=_ts(11), method=NewsCanonicalizationMethod.EXACT_BODY_TEXT
    )
    with pytest.raises(NewsCanonicalRelationConflictError):
        await canon_repo.add_relation_vintage(conflicting)


async def test_no_update_path_repeated_add_never_mutates_row(
    news_repo: SqlAlchemyNewsRepository,
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
) -> None:
    # Section 50: there must be no UPDATE path -- confirmed indirectly
    # here by proving a second, identical add never changes the row
    # count or any stored field (an idempotent INSERT ... ON CONFLICT
    # DO NOTHING, never an UPDATE).
    a = await _make_item(news_repo, "noupdate-a", availability=_ts(10))
    b = await _make_item(news_repo, "noupdate-b", availability=_ts(10))
    relation = _relation(a, b, availability=_ts(11))
    await canon_repo.add_relation_vintage(relation)
    await canon_repo.add_relation_vintage(relation)
    await canon_repo.add_relation_vintage(relation)

    stored = await canon_repo.list_relation_vintages_for_pair(
        relation.left_news_item_key, relation.right_news_item_key
    )
    assert len(stored) == 1
    assert stored[0] == relation


# --- Concurrency (Section 52) -------------------------------------------------


async def test_concurrent_identical_relation_creation_is_safe(
    news_repo: SqlAlchemyNewsRepository,
) -> None:
    a = await _make_item(news_repo, "concurrent-a", availability=_ts(10))
    b = await _make_item(news_repo, "concurrent-b", availability=_ts(10))
    relation = _relation(a, b, availability=_ts(11))

    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)

    async def _write() -> bool:
        async with session_factory() as own_session:
            own_news_repo = SqlAlchemyNewsRepository(own_session)
            own_canon_repo = SqlAlchemyNewsCanonicalizationRepository(own_session, own_news_repo)
            result = await own_canon_repo.add_relation_vintage(relation)
            return result.inserted

    results = await asyncio.gather(_write(), _write())
    assert sorted(results) == [False, True]  # exactly one real insert, one idempotent no-op

    session_factory_check = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    async with session_factory_check() as check_session:
        check_news_repo = SqlAlchemyNewsRepository(check_session)
        check_canon_repo = SqlAlchemyNewsCanonicalizationRepository(check_session, check_news_repo)
        stored = await check_canon_repo.list_relation_vintages_for_pair(
            relation.left_news_item_key, relation.right_news_item_key
        )
        assert len(stored) == 1


# --- Candidate-state semantics (Section 55) -----------------------------------


async def test_quarantined_only_vintage_excludes_the_item_entirely(
    news_repo: SqlAlchemyNewsRepository,
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
) -> None:
    # The ONLY vintage is quarantined -- no evidence-eligible vintage
    # exists at all as of this instant, so the item is excluded.
    key = await _make_item(
        news_repo,
        "quarantine-only",
        availability=_ts(10),
        evidence_disposition=NewsEvidenceDisposition.QUARANTINED,
        quarantine_reason="test quarantine",
    )
    candidates = await canon_repo.list_candidates_as_of(_ts(12))
    assert key not in {c.news_item_key for c in candidates}


async def test_quarantined_latest_vintage_falls_back_to_earlier_eligible_vintage(
    news_repo: SqlAlchemyNewsRepository,
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
) -> None:
    # Section 27's own explicit instruction: "mirror the existing
    # evidence-eligible query's actual semantics... do not invent a
    # second interpretation." The ALREADY-SHIPPED FX-56 semantics of
    # `latest_evidence_eligible_vintage_as_of` fall back to an EARLIER
    # evidence-eligible vintage when the item's own OVERALL latest
    # vintage (as of this instant) is quarantined -- this is not a
    # new rule FX-58 invents; it is the exact existing contract,
    # reused unmodified, confirmed here end-to-end through the real
    # FX-58 candidate query.
    key = await _make_item(
        news_repo, "quarantine-fallback", availability=_ts(10), headline="Original"
    )
    quarantined_vintage = NewsItemVintage(
        news_item_key=key,
        revision_sequence=1,
        availability=_ts(11),
        observation_mode=NewsObservationMode.PROSPECTIVE,
        headline="Original",
        source_channel="test_channel",
        observed_source_channels=("test_channel",),
        source_status=NewsSourceStatus.ACTIVE,
        evidence_disposition=NewsEvidenceDisposition.QUARANTINED,
        quarantine_reason="test quarantine",
    )
    await news_repo.add_vintage(quarantined_vintage)

    candidates = await canon_repo.list_candidates_as_of(_ts(12))
    matching = [c for c in candidates if c.news_item_key == key]
    assert len(matching) == 1
    assert matching[0].revision_sequence == 0  # the earlier, still-eligible vintage


async def test_backfill_excluded_by_default(
    news_repo: SqlAlchemyNewsRepository,
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
) -> None:
    key = await _make_item(
        news_repo,
        "backfill-a",
        availability=_ts(10),
        observation_mode=NewsObservationMode.BACKFILL,
    )
    candidates = await canon_repo.list_candidates_as_of(_ts(12))
    assert key not in {c.news_item_key for c in candidates}

    candidates_incl = await canon_repo.list_candidates_as_of(_ts(12), include_backfill=True)
    assert key in {c.news_item_key for c in candidates_incl}


async def test_prospective_evidence_eligible_item_is_included(
    news_repo: SqlAlchemyNewsRepository,
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
) -> None:
    key = await _make_item(news_repo, "eligible-a", availability=_ts(10))
    candidates = await canon_repo.list_candidates_as_of(_ts(12))
    assert key in {c.news_item_key for c in candidates}
