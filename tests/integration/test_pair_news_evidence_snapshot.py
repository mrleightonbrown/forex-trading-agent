"""FX-60 Sections 58-68/73/78: real-Postgres end-to-end tests for
`GetPairNewsEvidenceSnapshot`, covering the mandatory PIT worked
examples this story's own spec calls out explicitly -- same-story/
not-same-story relation PIT, transitive/contradictory grouping,
window/dedup (the critical late-duplicate-does-not-revive-an-old-
story example), correction-does-not-revive, source-published-time-
does-not-control-window, semantic-availability PIT, stale-semantics
PIT, backfill window-anchor exclusion, and the algorithm-version PIT
example -- plus a full chain proving the use case mutates no stored
evidence.

Requires a live Postgres with migration `4b2621787a37` applied (the
current head; FX-60 adds none of its own, Section 2)."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.application.use_cases.get_pair_news_evidence_snapshot import (
    GetPairNewsEvidenceSnapshot,
    NewsPairSemanticCoverage,
)
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.news_canonical_grouping import NewsCanonicalizationInconsistentStateError
from forex_agent.domain.news_canonical_relation_kind import NewsCanonicalRelationKind
from forex_agent.domain.news_canonical_relation_vintage import NewsCanonicalRelationVintage
from forex_agent.domain.news_canonicalization_method import NewsCanonicalizationMethod
from forex_agent.domain.news_currency_relevance import NewsCurrencyRelevance
from forex_agent.domain.news_currency_relevance_reason import NewsCurrencyRelevanceReason
from forex_agent.domain.news_entity_annotation import NewsEntityAnnotation
from forex_agent.domain.news_entity_evidence_kind import NewsEntityEvidenceKind
from forex_agent.domain.news_entity_type import NewsEntityType
from forex_agent.domain.news_evidence_disposition import NewsEvidenceDisposition
from forex_agent.domain.news_item_vintage import NewsItemVintage
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.news_pair_relevance import NewsPairRelevanceSide
from forex_agent.domain.news_semantic_annotation_vintage import NewsSemanticAnnotationVintage
from forex_agent.domain.news_semantic_classification import NewsSemanticClassification
from forex_agent.domain.news_source_identity import NewsSourceIdentity
from forex_agent.domain.news_source_status import NewsSourceStatus
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.models.news_canonical_relation_vintage import (
    NewsCanonicalRelationVintageRow,
)
from forex_agent.infrastructure.db.models.news_item import NewsItemRow
from forex_agent.infrastructure.db.models.news_item_vintage import NewsItemVintageRow
from forex_agent.infrastructure.db.models.news_semantic_annotation_vintage import (
    NewsSemanticAnnotationVintageRow,
)
from forex_agent.infrastructure.db.models.news_source_mapping import NewsSourceMappingRow
from forex_agent.infrastructure.db.news_canonicalization_repository import (
    SqlAlchemyNewsCanonicalizationRepository,
)
from forex_agent.infrastructure.db.news_repository import SqlAlchemyNewsRepository
from forex_agent.infrastructure.db.news_semantic_repository import SqlAlchemyNewsSemanticRepository
from forex_agent.infrastructure.db.session import get_engine

TEST_SOURCE_KEY = "__fx60_snapshot_test__"
EURUSD = Instrument(base_currency="EUR", quote_currency="USD")


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
                delete(NewsSemanticAnnotationVintageRow).where(
                    NewsSemanticAnnotationVintageRow.news_item_key == key
                )
            )
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


@pytest.fixture
def semantic_repo(
    session: AsyncSession, news_repo: SqlAlchemyNewsRepository
) -> SqlAlchemyNewsSemanticRepository:
    return SqlAlchemyNewsSemanticRepository(session, news_repo)


@pytest.fixture
def get_snapshot(
    news_repo: SqlAlchemyNewsRepository,
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
    semantic_repo: SqlAlchemyNewsSemanticRepository,
) -> GetPairNewsEvidenceSnapshot:
    return GetPairNewsEvidenceSnapshot(news_repo, canon_repo, semantic_repo)


async def _make_item(
    news_repo: SqlAlchemyNewsRepository,
    suffix: str,
    *,
    first_seen_at: UtcTimestamp,
    headline: str = "H",
    source_status: NewsSourceStatus = NewsSourceStatus.ACTIVE,
    observation_mode: NewsObservationMode = NewsObservationMode.PROSPECTIVE,
    evidence_disposition: NewsEvidenceDisposition = NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
    source_published_at: UtcTimestamp | None = None,
) -> str:
    registration = await news_repo._register_source_item_for_test_setup(
        _identity(suffix), first_seen_at, observation_mode
    )
    vintage = NewsItemVintage(
        news_item_key=registration.news_item_key,
        revision_sequence=0,
        availability=first_seen_at,
        observation_mode=observation_mode,
        headline=headline,
        source_channel="test_channel",
        observed_source_channels=("test_channel",),
        source_status=source_status,
        evidence_disposition=evidence_disposition,
        source_published_at=source_published_at,
        quarantine_reason=(
            "test fixture" if evidence_disposition is NewsEvidenceDisposition.QUARANTINED else None
        ),
    )
    await news_repo.add_vintage(vintage)
    return registration.news_item_key


async def _append_revision(
    news_repo: SqlAlchemyNewsRepository,
    news_item_key: str,
    *,
    revision_sequence: int,
    availability: UtcTimestamp,
    headline: str = "H (updated)",
    source_status: NewsSourceStatus = NewsSourceStatus.ACTIVE,
    source_published_at: UtcTimestamp | None = None,
) -> None:
    vintage = NewsItemVintage(
        news_item_key=news_item_key,
        revision_sequence=revision_sequence,
        availability=availability,
        observation_mode=NewsObservationMode.PROSPECTIVE,
        headline=headline,
        source_channel="test_channel",
        observed_source_channels=("test_channel",),
        source_status=source_status,
        evidence_disposition=NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
        source_published_at=source_published_at,
    )
    await news_repo.add_vintage(vintage)


def _classification(
    currency_code: str = "USD",
    institution: str = "FEDERAL_RESERVE",
    jurisdiction: str = "UNITED_STATES",
) -> NewsSemanticClassification:
    return NewsSemanticClassification(
        entities=(
            NewsEntityAnnotation(
                entity_type=NewsEntityType.INSTITUTION,
                entity_key=institution,
                evidence=(NewsEntityEvidenceKind.SOURCE_PROFILE,),
            ),
            NewsEntityAnnotation(
                entity_type=NewsEntityType.JURISDICTION,
                entity_key=jurisdiction,
                evidence=(NewsEntityEvidenceKind.SOURCE_PROFILE,),
            ),
        ),
        topics=(),
        currency_relevance=(
            NewsCurrencyRelevance(
                currency_code=currency_code,
                reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,),
            ),
        ),
    )


async def _add_annotation(
    semantic_repo: SqlAlchemyNewsSemanticRepository,
    news_item_key: str,
    *,
    availability: UtcTimestamp,
    basis_news_item_revision_sequence: int = 0,
    classification: NewsSemanticClassification | None = None,
    algorithm_version: str = "fx59_v1",
    revision_sequence: int = 0,
) -> None:
    await semantic_repo.add_annotation_vintage(
        NewsSemanticAnnotationVintage(
            news_item_key=news_item_key,
            revision_sequence=revision_sequence,
            availability=availability,
            basis_news_item_revision_sequence=basis_news_item_revision_sequence,
            algorithm_version=algorithm_version,
            classification=classification or _classification(),
        )
    )


async def _add_relation(
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
    left: str,
    right: str,
    *,
    availability: UtcTimestamp,
    relation_kind: NewsCanonicalRelationKind = NewsCanonicalRelationKind.SAME_STORY,
    method: NewsCanonicalizationMethod = NewsCanonicalizationMethod.EXACT_CANONICAL_URL,
    revision_sequence: int = 0,
) -> None:
    left_key, right_key = sorted((left, right))
    await canon_repo.add_relation_vintage(
        NewsCanonicalRelationVintage(
            left_news_item_key=left_key,
            right_news_item_key=right_key,
            revision_sequence=revision_sequence,
            availability=availability,
            relation_kind=relation_kind,
            method=method,
            left_item_revision_sequence=0,
            right_item_revision_sequence=0,
            algorithm_version="fx58_v2",
        )
    )


# --- Section 58: same-story relation PIT -------------------------------------


async def test_same_story_relation_pit(
    news_repo: SqlAlchemyNewsRepository,
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
    semantic_repo: SqlAlchemyNewsSemanticRepository,
    get_snapshot: GetPairNewsEvidenceSnapshot,
) -> None:
    a = await _make_item(news_repo, "same-a", first_seen_at=_ts(9))
    b = await _make_item(news_repo, "same-b", first_seen_at=_ts(9, 10))
    await _add_annotation(semantic_repo, a, availability=_ts(9, 5))
    await _add_annotation(semantic_repo, b, availability=_ts(9, 15))

    before_relation = await get_snapshot(EURUSD, _ts(0), _ts(9, 20))
    assert len(before_relation.active_entries) == 2

    await _add_relation(canon_repo, a, b, availability=_ts(9, 30))

    after_relation = await get_snapshot(EURUSD, _ts(0), _ts(9, 40))
    assert len(after_relation.active_entries) == 1
    assert set(after_relation.active_entries[0].member_news_item_keys) == {a, b}

    # Historical query before the relation existed remains two groups.
    historical = await get_snapshot(EURUSD, _ts(0), _ts(9, 20))
    assert len(historical.active_entries) == 2


# --- Section 59: not-same correction PIT -------------------------------------


async def test_not_same_correction_pit(
    news_repo: SqlAlchemyNewsRepository,
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
    semantic_repo: SqlAlchemyNewsSemanticRepository,
    get_snapshot: GetPairNewsEvidenceSnapshot,
) -> None:
    a = await _make_item(news_repo, "notsame-a", first_seen_at=_ts(9))
    b = await _make_item(news_repo, "notsame-b", first_seen_at=_ts(9, 10))
    await _add_annotation(semantic_repo, a, availability=_ts(9, 5))
    await _add_annotation(semantic_repo, b, availability=_ts(9, 15))
    await _add_relation(canon_repo, a, b, availability=_ts(9, 30))

    before_t2 = await get_snapshot(EURUSD, _ts(0), _ts(9, 40))
    assert len(before_t2.active_entries) == 1

    await _add_relation(
        canon_repo,
        a,
        b,
        availability=_ts(10),
        relation_kind=NewsCanonicalRelationKind.NOT_SAME_STORY,
        method=NewsCanonicalizationMethod.MANUAL_REVIEW,
        revision_sequence=1,
    )

    after_t2 = await get_snapshot(EURUSD, _ts(0), _ts(10, 10))
    assert len(after_t2.active_entries) == 2


# --- Section 60: transitive group ---------------------------------------------


async def test_transitive_group(
    news_repo: SqlAlchemyNewsRepository,
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
    semantic_repo: SqlAlchemyNewsSemanticRepository,
    get_snapshot: GetPairNewsEvidenceSnapshot,
) -> None:
    a = await _make_item(news_repo, "trans-a", first_seen_at=_ts(9))
    b = await _make_item(news_repo, "trans-b", first_seen_at=_ts(9, 10))
    c = await _make_item(news_repo, "trans-c", first_seen_at=_ts(9, 20))
    for key in (a, b, c):
        await _add_annotation(semantic_repo, key, availability=_ts(9, 25))
    await _add_relation(canon_repo, a, b, availability=_ts(9, 30))
    await _add_relation(canon_repo, b, c, availability=_ts(9, 35))

    snapshot = await get_snapshot(EURUSD, _ts(0), _ts(9, 40))

    assert len(snapshot.active_entries) == 1
    assert set(snapshot.active_entries[0].member_news_item_keys) == {a, b, c}


# --- Section 61: contradictory group fails closed -----------------------------


async def test_contradictory_group_fails_closed(
    news_repo: SqlAlchemyNewsRepository,
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
    semantic_repo: SqlAlchemyNewsSemanticRepository,
    get_snapshot: GetPairNewsEvidenceSnapshot,
) -> None:
    a = await _make_item(news_repo, "contra-a", first_seen_at=_ts(9))
    b = await _make_item(news_repo, "contra-b", first_seen_at=_ts(9, 10))
    c = await _make_item(news_repo, "contra-c", first_seen_at=_ts(9, 20))
    for key in (a, b, c):
        await _add_annotation(semantic_repo, key, availability=_ts(9, 25))
    await _add_relation(canon_repo, a, b, availability=_ts(9, 30))
    await _add_relation(canon_repo, b, c, availability=_ts(9, 35))
    await _add_relation(
        canon_repo,
        a,
        c,
        availability=_ts(9, 40),
        relation_kind=NewsCanonicalRelationKind.NOT_SAME_STORY,
        method=NewsCanonicalizationMethod.MANUAL_REVIEW,
    )

    with pytest.raises(NewsCanonicalizationInconsistentStateError):
        await get_snapshot(EURUSD, _ts(0), _ts(9, 45))


# --- Section 62: window/dedup worked example (critical) ----------------------


async def test_window_dedup_worked_example(
    news_repo: SqlAlchemyNewsRepository,
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
    semantic_repo: SqlAlchemyNewsSemanticRepository,
    get_snapshot: GetPairNewsEvidenceSnapshot,
) -> None:
    a = await _make_item(news_repo, "dedup-a", first_seen_at=_ts(8))
    b = await _make_item(news_repo, "dedup-b", first_seen_at=_ts(10))
    await _add_annotation(semantic_repo, a, availability=_ts(8, 5))
    await _add_annotation(semantic_repo, b, availability=_ts(10, 5))

    window_start, window_as_of = _ts(9), _ts(11)

    # Before the SAME_STORY relation is known, B alone may appear
    # (A is outside the window; B is inside it).
    before = await get_snapshot(EURUSD, window_start, window_as_of)
    before_keys = {k for e in before.active_entries for k in e.member_news_item_keys}
    assert b in before_keys
    assert a not in before_keys

    # Once A and B are known to be the SAME story, the merged group's
    # own story_first_seen_at is A's 08:00 -- OUTSIDE the window -- so
    # the merged story must NOT appear, even though B's own arrival
    # (10:00) is inside the window.
    await _add_relation(canon_repo, a, b, availability=_ts(11, 30))

    after = await get_snapshot(EURUSD, window_start, _ts(12))
    after_keys = {k for e in after.active_entries for k in e.member_news_item_keys}
    assert a not in after_keys
    assert b not in after_keys
    assert after.groups_outside_window >= 1


# --- Section 63: correction does not revive an old story ----------------------


async def test_correction_does_not_revive_old_story(
    news_repo: SqlAlchemyNewsRepository,
    semantic_repo: SqlAlchemyNewsSemanticRepository,
    get_snapshot: GetPairNewsEvidenceSnapshot,
) -> None:
    item = await _make_item(news_repo, "revive-1", first_seen_at=_ts(8))
    await _append_revision(news_repo, item, revision_sequence=1, availability=_ts(11))
    await _add_annotation(
        semantic_repo, item, availability=_ts(11, 5), basis_news_item_revision_sequence=1
    )

    # A window scoped ONLY to the correction's own arrival time --
    # the item must still be excluded, since its story age is 08:00.
    snapshot = await get_snapshot(EURUSD, _ts(10, 30), _ts(12))

    keys = {k for e in snapshot.active_entries for k in e.member_news_item_keys}
    assert item not in keys


# --- Section 64: source-published time does not control the window ----------


async def test_source_published_time_does_not_control_window(
    news_repo: SqlAlchemyNewsRepository,
    semantic_repo: SqlAlchemyNewsSemanticRepository,
    get_snapshot: GetPairNewsEvidenceSnapshot,
) -> None:
    # first_seen_at=10:00, but source_published_at claims the prior day.
    item = await _make_item(
        news_repo,
        "pubtime-1",
        first_seen_at=_ts(10),
        source_published_at=UtcTimestamp(datetime(2025, 12, 31, 9, tzinfo=UTC)),
    )
    await _add_annotation(semantic_repo, item, availability=_ts(10, 5))

    included = await get_snapshot(EURUSD, _ts(9), _ts(11))
    keys = {k for e in included.active_entries for k in e.member_news_item_keys}
    assert item in keys

    # Opposite: first_seen_at is old, but source_published_at claims "now".
    old_item = await _make_item(
        news_repo,
        "pubtime-2",
        first_seen_at=_ts(1),
        source_published_at=_ts(10, 30),
    )
    await _add_annotation(semantic_repo, old_item, availability=_ts(1, 5))

    excluded = await get_snapshot(EURUSD, _ts(9), _ts(11))
    excluded_keys = {k for e in excluded.active_entries for k in e.member_news_item_keys}
    assert old_item not in excluded_keys


# --- Section 65: semantic availability PIT -----------------------------------


async def test_semantic_availability_pit(
    news_repo: SqlAlchemyNewsRepository,
    semantic_repo: SqlAlchemyNewsSemanticRepository,
    get_snapshot: GetPairNewsEvidenceSnapshot,
) -> None:
    item = await _make_item(news_repo, "semavail-1", first_seen_at=_ts(9))
    await _add_annotation(semantic_repo, item, availability=_ts(9, 10))

    before = await get_snapshot(EURUSD, _ts(0), _ts(9, 5))
    assert before.coverage is NewsPairSemanticCoverage.INCOMPLETE_SEMANTICS
    assert any(g.news_item_key == item for g in before.semantic_gaps)
    before_keys = {k for e in before.active_entries for k in e.member_news_item_keys}
    assert item not in before_keys

    after = await get_snapshot(EURUSD, _ts(0), _ts(9, 15))
    assert after.coverage is NewsPairSemanticCoverage.COMPLETE
    after_keys = {k for e in after.active_entries for k in e.member_news_item_keys}
    assert item in after_keys


# --- Section 66: stale semantics PIT -----------------------------------------


async def test_stale_semantics_pit(
    news_repo: SqlAlchemyNewsRepository,
    semantic_repo: SqlAlchemyNewsSemanticRepository,
    get_snapshot: GetPairNewsEvidenceSnapshot,
) -> None:
    item = await _make_item(news_repo, "stale-1", first_seen_at=_ts(9))
    await _add_annotation(
        semantic_repo, item, availability=_ts(9, 5), basis_news_item_revision_sequence=0
    )

    current = await get_snapshot(EURUSD, _ts(0), _ts(9, 10))
    assert current.coverage is NewsPairSemanticCoverage.COMPLETE

    await _append_revision(news_repo, item, revision_sequence=1, availability=_ts(9, 20))

    stale = await get_snapshot(EURUSD, _ts(0), _ts(9, 25))
    assert stale.coverage is NewsPairSemanticCoverage.INCOMPLETE_SEMANTICS
    stale_keys = {k for e in stale.active_entries for k in e.member_news_item_keys}
    assert item not in stale_keys
    assert any(g.news_item_key == item for g in stale.semantic_gaps)

    await _add_annotation(
        semantic_repo,
        item,
        availability=_ts(9, 30),
        basis_news_item_revision_sequence=1,
        revision_sequence=1,
    )

    reclassified = await get_snapshot(EURUSD, _ts(0), _ts(9, 35))
    assert reclassified.coverage is NewsPairSemanticCoverage.COMPLETE
    reclassified_keys = {k for e in reclassified.active_entries for k in e.member_news_item_keys}
    assert item in reclassified_keys


# --- Section 68: backfill window-anchor exclusion -----------------------------


async def test_backfill_window_anchor_exclusion(
    news_repo: SqlAlchemyNewsRepository,
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
    semantic_repo: SqlAlchemyNewsSemanticRepository,
    get_snapshot: GetPairNewsEvidenceSnapshot,
) -> None:
    backfill_item = await _make_item(
        news_repo,
        "backfill-1",
        first_seen_at=_ts(1),
        observation_mode=NewsObservationMode.BACKFILL,
    )
    prospective_item = await _make_item(news_repo, "backfill-2", first_seen_at=_ts(9, 30))
    await _add_annotation(semantic_repo, backfill_item, availability=_ts(1, 5))
    await _add_annotation(semantic_repo, prospective_item, availability=_ts(9, 35))
    await _add_relation(canon_repo, backfill_item, prospective_item, availability=_ts(10))

    snapshot = await get_snapshot(EURUSD, _ts(9), _ts(10, 30), include_backfill=False)

    assert len(snapshot.active_entries) == 1
    entry = snapshot.active_entries[0]
    # The backfill member is excluded from snapshot eligibility
    # entirely -- the window anchor comes from the prospective member
    # alone, not suppressed by the much-earlier backfill one.
    assert backfill_item not in entry.member_news_item_keys
    assert entry.story_first_seen_at == _ts(9, 30)


# --- Section 73: algorithm-version PIT ---------------------------------------


async def test_algorithm_version_pit(
    news_repo: SqlAlchemyNewsRepository,
    semantic_repo: SqlAlchemyNewsSemanticRepository,
    get_snapshot: GetPairNewsEvidenceSnapshot,
) -> None:
    item = await _make_item(news_repo, "algver-1", first_seen_at=_ts(9))
    await _add_annotation(semantic_repo, item, availability=_ts(10), algorithm_version="fx59_v1")
    await _add_annotation(
        semantic_repo,
        item,
        availability=_ts(11),
        algorithm_version="fx59_v2",
        revision_sequence=1,
    )

    between = await get_snapshot(EURUSD, _ts(0), _ts(10, 30))
    assert between.active_entries[0].members[0].semantic_algorithm_version == "fx59_v1"

    after = await get_snapshot(EURUSD, _ts(0), _ts(11, 30))
    assert after.active_entries[0].members[0].semantic_algorithm_version == "fx59_v2"


# --- Section 78: full chain, no mutation -------------------------------------


async def test_full_chain_mutates_no_stored_evidence(
    news_repo: SqlAlchemyNewsRepository,
    semantic_repo: SqlAlchemyNewsSemanticRepository,
    get_snapshot: GetPairNewsEvidenceSnapshot,
) -> None:
    item = await _make_item(news_repo, "nomutate-1", first_seen_at=_ts(9))
    await _add_annotation(semantic_repo, item, availability=_ts(9, 5))

    before_vintages = await news_repo.list_vintages(item)
    before_annotations = await semantic_repo.list_annotation_vintages_for_item(item)

    await get_snapshot(EURUSD, _ts(0), _ts(10))
    await get_snapshot(EURUSD, _ts(0), _ts(10))  # a second call changes nothing further

    after_vintages = await news_repo.list_vintages(item)
    after_annotations = await semantic_repo.list_annotation_vintages_for_item(item)

    assert before_vintages == after_vintages
    assert before_annotations == after_annotations


async def test_pair_side_classification_through_real_postgres(
    news_repo: SqlAlchemyNewsRepository,
    semantic_repo: SqlAlchemyNewsSemanticRepository,
    get_snapshot: GetPairNewsEvidenceSnapshot,
) -> None:
    eur_item = await _make_item(news_repo, "side-eur", first_seen_at=_ts(9))
    await _add_annotation(
        semantic_repo, eur_item, availability=_ts(9, 5), classification=_classification("EUR")
    )

    snapshot = await get_snapshot(EURUSD, _ts(0), _ts(10))

    assert snapshot.active_entries[0].pair_relevance_side is NewsPairRelevanceSide.BASE_ONLY


# --- FX-60H H2: canonical relation provenance, real Postgres -----------------


async def test_relation_provenance_pit_against_real_postgres(
    news_repo: SqlAlchemyNewsRepository,
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
    semantic_repo: SqlAlchemyNewsSemanticRepository,
    get_snapshot: GetPairNewsEvidenceSnapshot,
) -> None:
    """A relation whose own `availability` is after a requested
    `as_of` must not appear in that earlier snapshot's own
    `relation_provenance` -- proven against real Postgres, not just
    the in-memory fakes, since `relation_provenance` is built from
    `list_latest_relation_states_as_of(as_of)`, a real SQL query."""
    a = await _make_item(news_repo, "prov-a", first_seen_at=_ts(9))
    b = await _make_item(news_repo, "prov-b", first_seen_at=_ts(9, 10))
    await _add_annotation(semantic_repo, a, availability=_ts(9, 5))
    await _add_annotation(semantic_repo, b, availability=_ts(9, 15))

    before_relation = await get_snapshot(EURUSD, _ts(0), _ts(9, 20))
    assert len(before_relation.active_entries) == 2
    for entry in before_relation.active_entries:
        assert entry.relation_provenance == ()

    await _add_relation(canon_repo, a, b, availability=_ts(9, 30))

    # Re-querying the SAME earlier `as_of` still shows no provenance --
    # the relation itself did not exist yet at that instant.
    still_before = await get_snapshot(EURUSD, _ts(0), _ts(9, 20))
    assert len(still_before.active_entries) == 2
    for entry in still_before.active_entries:
        assert entry.relation_provenance == ()

    after_relation = await get_snapshot(EURUSD, _ts(0), _ts(9, 40))
    assert len(after_relation.active_entries) == 1
    provenance = after_relation.active_entries[0].relation_provenance
    assert len(provenance) == 1
    # `NewsCanonicalRelationVintage` stores left/right lexicographically
    # sorted by news_item_key, not by call-argument order (Section 58).
    assert {provenance[0].left_news_item_key, provenance[0].right_news_item_key} == {a, b}


async def test_relation_provenance_transitive_real_edges_only_against_real_postgres(
    news_repo: SqlAlchemyNewsRepository,
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
    semantic_repo: SqlAlchemyNewsSemanticRepository,
    get_snapshot: GetPairNewsEvidenceSnapshot,
) -> None:
    a = await _make_item(news_repo, "transprov-a", first_seen_at=_ts(9))
    b = await _make_item(news_repo, "transprov-b", first_seen_at=_ts(9, 10))
    c = await _make_item(news_repo, "transprov-c", first_seen_at=_ts(9, 20))
    for key in (a, b, c):
        await _add_annotation(semantic_repo, key, availability=_ts(9, 25))
    await _add_relation(canon_repo, a, b, availability=_ts(9, 30))
    await _add_relation(canon_repo, b, c, availability=_ts(9, 35))

    snapshot = await get_snapshot(EURUSD, _ts(0), _ts(9, 40))

    assert len(snapshot.active_entries) == 1
    group = snapshot.active_entries[0]
    assert set(group.member_news_item_keys) == {a, b, c}
    # Compare as orientation-agnostic frozensets -- `NewsCanonicalRelat
    # ionVintage` stores left/right lexicographically sorted by news_
    # item_key, not by call-argument order (Section 58).
    provenance_pairs = {
        frozenset((r.left_news_item_key, r.right_news_item_key)) for r in group.relation_provenance
    }
    assert provenance_pairs == {frozenset((a, b)), frozenset((b, c))}
    assert frozenset((a, c)) not in provenance_pairs


# --- FX-60H H1: real-Postgres accounting reconciliation -----------------------


async def test_accounting_reconciles_against_real_postgres(
    news_repo: SqlAlchemyNewsRepository,
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
    semantic_repo: SqlAlchemyNewsSemanticRepository,
    get_snapshot: GetPairNewsEvidenceSnapshot,
) -> None:
    """Exercises every group disposition bucket against real Postgres
    in one snapshot -- construction itself would fail closed on any
    arithmetic drift (`NewsPairSnapshotAccounting.__post_init__`), so
    a successful call plus these explicit assertions prove the
    invariant holds for the real SQL-backed batch repository paths,
    not merely the in-memory fakes."""
    singleton = await _make_item(news_repo, "acct-singleton", first_seen_at=_ts(9))
    await _add_annotation(
        semantic_repo, singleton, availability=_ts(9, 1), classification=_classification("USD")
    )

    dup_a = await _make_item(news_repo, "acct-dup-a", first_seen_at=_ts(9, 10))
    dup_b = await _make_item(news_repo, "acct-dup-b", first_seen_at=_ts(9, 15))
    await _add_relation(canon_repo, dup_a, dup_b, availability=_ts(9, 20))
    await _add_annotation(
        semantic_repo, dup_a, availability=_ts(9, 11), classification=_classification("USD")
    )
    await _add_annotation(
        semantic_repo, dup_b, availability=_ts(9, 16), classification=_classification("USD")
    )

    out_of_window = await _make_item(news_repo, "acct-outwin", first_seen_at=_ts(1))
    await _add_annotation(semantic_repo, out_of_window, availability=_ts(1, 1))

    await _make_item(
        news_repo,
        "acct-quarantined",
        first_seen_at=_ts(9, 25),
        evidence_disposition=NewsEvidenceDisposition.QUARANTINED,
    )

    irrelevant = await _make_item(news_repo, "acct-irrelevant", first_seen_at=_ts(9, 30))
    await _add_annotation(
        semantic_repo, irrelevant, availability=_ts(9, 31), classification=_classification("CAD")
    )

    await _make_item(news_repo, "acct-incomplete", first_seen_at=_ts(9, 40))
    # No annotation at all -> UNCLASSIFIED, no confirmed relevance.

    snapshot = await get_snapshot(EURUSD, _ts(5), _ts(10))

    acc = snapshot.accounting
    assert acc.groups_total == 6
    assert acc.groups_outside_window == 1
    assert acc.groups_without_eligible_evidence == 1
    assert acc.groups_pair_irrelevant == 1
    assert acc.groups_incomplete_semantics == 1
    assert (
        acc.groups_base_only + acc.groups_quote_only + acc.groups_both == 2
    )  # singleton + dup group
    assert (
        acc.groups_outside_window
        + acc.groups_without_eligible_evidence
        + acc.groups_pair_irrelevant
        + acc.groups_incomplete_semantics
        + acc.groups_base_only
        + acc.groups_quote_only
        + acc.groups_both
        == acc.groups_total
    )


# --- FX-60H.1: canonical membership vs evidence eligibility, real Postgres ---


async def test_h2_1_ineligible_intermediate_member_real_postgres(
    news_repo: SqlAlchemyNewsRepository,
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
    semantic_repo: SqlAlchemyNewsSemanticRepository,
    get_snapshot: GetPairNewsEvidenceSnapshot,
) -> None:
    """Mandatory example, real Postgres: A-SAME-B-SAME-C with B
    QUARANTINED (never evidence-eligible). One canonical group forms;
    only A and C contribute evidence; `relation_provenance` must
    still retain BOTH the A-B and B-C edges."""
    a = await _make_item(news_repo, "h2x1-a", first_seen_at=_ts(9))
    b = await _make_item(
        news_repo,
        "h2x1-b",
        first_seen_at=_ts(9, 5),
        evidence_disposition=NewsEvidenceDisposition.QUARANTINED,
    )
    c = await _make_item(news_repo, "h2x1-c", first_seen_at=_ts(9, 10))
    await _add_relation(canon_repo, a, b, availability=_ts(9, 20))
    await _add_relation(canon_repo, b, c, availability=_ts(9, 25))
    await _add_annotation(semantic_repo, a, availability=_ts(9, 1))
    await _add_annotation(semantic_repo, c, availability=_ts(9, 11))

    snapshot = await get_snapshot(EURUSD, _ts(0), _ts(10))

    assert snapshot.accounting.groups_total == 1
    assert len(snapshot.active_entries) == 1
    entry = snapshot.active_entries[0]

    assert set(entry.member_news_item_keys) == {a, c}
    assert set(entry.canonical_member_news_item_keys) == {a, b, c}
    assert b not in {m.news_item_key for m in entry.members}
    assert b not in entry.semantic_gap_member_keys

    provenance_pairs = {
        frozenset((r.left_news_item_key, r.right_news_item_key)) for r in entry.relation_provenance
    }
    assert provenance_pairs == {frozenset((a, b)), frozenset((b, c))}


async def test_h2_3_future_relationship_with_ineligible_connector_real_postgres(
    news_repo: SqlAlchemyNewsRepository,
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
    semantic_repo: SqlAlchemyNewsSemanticRepository,
    get_snapshot: GetPairNewsEvidenceSnapshot,
) -> None:
    """A-SAME-B exists early (B ineligible throughout); B-SAME-C is
    added only LATER. At the earlier `as_of`, the canonical group is
    {A, B} only, with provenance containing just the A-B edge.
    Reconstructing that SAME earlier `as_of` again, after the future
    relation is added, must produce an unchanged result."""
    a = await _make_item(news_repo, "h2x3-a", first_seen_at=_ts(9))
    b = await _make_item(
        news_repo,
        "h2x3-b",
        first_seen_at=_ts(9, 5),
        evidence_disposition=NewsEvidenceDisposition.QUARANTINED,
    )
    c = await _make_item(news_repo, "h2x3-c", first_seen_at=_ts(9, 10))
    await _add_relation(canon_repo, a, b, availability=_ts(9, 20))
    await _add_annotation(semantic_repo, a, availability=_ts(9, 1))
    await _add_annotation(semantic_repo, c, availability=_ts(9, 11))

    earlier_first = await get_snapshot(EURUSD, _ts(0), _ts(9, 30))
    assert earlier_first.accounting.groups_total == 2  # {A,B} and {C}
    a_entry_first = next(
        e for e in earlier_first.active_entries if a in e.canonical_member_news_item_keys
    )
    assert set(a_entry_first.canonical_member_news_item_keys) == {a, b}
    assert set(a_entry_first.member_news_item_keys) == {a}
    assert {
        frozenset((r.left_news_item_key, r.right_news_item_key))
        for r in a_entry_first.relation_provenance
    } == {frozenset((a, b))}

    # The future relationship, added AFTER the earlier as_of above.
    await _add_relation(canon_repo, b, c, availability=_ts(9, 40))

    # Reconstructing the SAME earlier as_of must be unchanged.
    earlier_second = await get_snapshot(EURUSD, _ts(0), _ts(9, 30))
    assert earlier_second.accounting.groups_total == 2
    a_entry_second = next(
        e for e in earlier_second.active_entries if a in e.canonical_member_news_item_keys
    )
    assert set(a_entry_second.canonical_member_news_item_keys) == {a, b}
    assert {
        frozenset((r.left_news_item_key, r.right_news_item_key))
        for r in a_entry_second.relation_provenance
    } == {frozenset((a, b))}

    # A later as_of now includes the future relation and all 3 members.
    later = await get_snapshot(EURUSD, _ts(0), _ts(10))
    assert later.accounting.groups_total == 1
    later_entry = later.active_entries[0]
    assert set(later_entry.canonical_member_news_item_keys) == {a, b, c}
    assert {
        frozenset((r.left_news_item_key, r.right_news_item_key))
        for r in later_entry.relation_provenance
    } == {frozenset((a, b)), frozenset((b, c))}


async def test_h2_4_multiple_connecting_paths_real_postgres(
    news_repo: SqlAlchemyNewsRepository,
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
    semantic_repo: SqlAlchemyNewsSemanticRepository,
    get_snapshot: GetPairNewsEvidenceSnapshot,
) -> None:
    """A fully-connected triangle (A-B, B-C, A-C all SAME_STORY) --
    provenance must list all three real edges exactly once each, with
    no duplicates, in canonical sorted order."""
    a = await _make_item(news_repo, "h2x4-a", first_seen_at=_ts(9))
    b = await _make_item(news_repo, "h2x4-b", first_seen_at=_ts(9, 5))
    c = await _make_item(news_repo, "h2x4-c", first_seen_at=_ts(9, 10))
    await _add_relation(canon_repo, a, b, availability=_ts(9, 20))
    await _add_relation(canon_repo, b, c, availability=_ts(9, 25))
    await _add_relation(canon_repo, a, c, availability=_ts(9, 30))
    for key, ts in ((a, _ts(9, 1)), (b, _ts(9, 6)), (c, _ts(9, 11))):
        await _add_annotation(semantic_repo, key, availability=ts)

    snapshot = await get_snapshot(EURUSD, _ts(0), _ts(10))

    assert len(snapshot.active_entries) == 1
    provenance = snapshot.active_entries[0].relation_provenance
    provenance_pairs = [(r.left_news_item_key, r.right_news_item_key) for r in provenance]
    assert len(provenance_pairs) == len(set(provenance_pairs))
    assert provenance_pairs == sorted(provenance_pairs)
    provenance_frozensets = {frozenset(p) for p in provenance_pairs}
    assert provenance_frozensets == {frozenset((a, b)), frozenset((b, c)), frozenset((a, c))}
