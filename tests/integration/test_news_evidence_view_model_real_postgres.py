"""FX-61 Sections 11.B/11.C: real-Postgres tests proving `build_news_
evidence_view` faithfully reflects the REAL `GetPairNewsEvidenceSnapshot`
output -- never re-deriving FX-60's own PIT/canonicalization/semantic
correctness (already exhaustively proven in `test_pair_news_evidence_
snapshot.py`), only proving the VIEW never drops, re-interprets, or
flattens anything the snapshot already established.

Section B directly protects the FX-60H.1 correction: an ineligible
intermediate member must remain visible in `canonical_member_news_
item_keys`/`relation_provenance` even though it contributes no
member detail.

Section C builds a T1-T4 historical sequence and re-renders the view
at each instant, proving `View(pair, window_start, T) = Present(FX60(
pair, window_start, T))` holds through the view-model layer too."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.application.use_cases.get_pair_news_evidence_snapshot import (
    GetPairNewsEvidenceSnapshot,
)
from forex_agent.apps.api.view_models.news_evidence_view_model import build_news_evidence_view
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.news_canonical_relation_kind import NewsCanonicalRelationKind
from forex_agent.domain.news_canonical_relation_vintage import NewsCanonicalRelationVintage
from forex_agent.domain.news_canonicalization_method import NewsCanonicalizationMethod
from forex_agent.domain.news_evidence_disposition import NewsEvidenceDisposition
from forex_agent.domain.news_item_vintage import NewsItemVintage
from forex_agent.domain.news_observation_mode import NewsObservationMode
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

TEST_SOURCE_KEY = "__fx61_news_view_test__"
EURUSD = Instrument(base_currency="EUR", quote_currency="USD")


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
    evidence_disposition: NewsEvidenceDisposition = NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
) -> str:
    registration = await news_repo._register_source_item_for_test_setup(
        _identity(suffix), first_seen_at, NewsObservationMode.PROSPECTIVE
    )
    vintage = NewsItemVintage(
        news_item_key=registration.news_item_key,
        revision_sequence=0,
        availability=first_seen_at,
        observation_mode=NewsObservationMode.PROSPECTIVE,
        headline=f"Headline {suffix}",
        source_channel="test_channel",
        observed_source_channels=("test_channel",),
        source_status=NewsSourceStatus.ACTIVE,
        evidence_disposition=evidence_disposition,
        canonical_url=f"https://example.com/{suffix}",
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
) -> None:
    vintage = NewsItemVintage(
        news_item_key=news_item_key,
        revision_sequence=revision_sequence,
        availability=availability,
        observation_mode=NewsObservationMode.PROSPECTIVE,
        headline="Headline (updated)",
        source_channel="test_channel",
        observed_source_channels=("test_channel",),
        source_status=NewsSourceStatus.ACTIVE,
        evidence_disposition=NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
    )
    await news_repo.add_vintage(vintage)


def _classification() -> NewsSemanticClassification:
    from forex_agent.domain.news_currency_relevance import NewsCurrencyRelevance
    from forex_agent.domain.news_currency_relevance_reason import NewsCurrencyRelevanceReason
    from forex_agent.domain.news_entity_annotation import NewsEntityAnnotation
    from forex_agent.domain.news_entity_evidence_kind import NewsEntityEvidenceKind
    from forex_agent.domain.news_entity_type import NewsEntityType

    return NewsSemanticClassification(
        entities=(
            NewsEntityAnnotation(
                entity_type=NewsEntityType.INSTITUTION,
                entity_key="FEDERAL_RESERVE",
                evidence=(NewsEntityEvidenceKind.SOURCE_PROFILE,),
            ),
            NewsEntityAnnotation(
                entity_type=NewsEntityType.JURISDICTION,
                entity_key="UNITED_STATES",
                evidence=(NewsEntityEvidenceKind.SOURCE_PROFILE,),
            ),
        ),
        topics=(),
        currency_relevance=(
            NewsCurrencyRelevance(
                currency_code="USD", reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,)
            ),
        ),
    )


async def _add_annotation(
    semantic_repo: SqlAlchemyNewsSemanticRepository,
    news_item_key: str,
    *,
    availability: UtcTimestamp,
    basis_news_item_revision_sequence: int = 0,
    revision_sequence: int = 0,
) -> None:
    await semantic_repo.add_annotation_vintage(
        NewsSemanticAnnotationVintage(
            news_item_key=news_item_key,
            revision_sequence=revision_sequence,
            availability=availability,
            basis_news_item_revision_sequence=basis_news_item_revision_sequence,
            algorithm_version="fx59_v1",
            classification=_classification(),
        )
    )


async def _add_relation(
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
    left: str,
    right: str,
    *,
    availability: UtcTimestamp,
) -> None:
    left_key, right_key = sorted((left, right))
    await canon_repo.add_relation_vintage(
        NewsCanonicalRelationVintage(
            left_news_item_key=left_key,
            right_news_item_key=right_key,
            revision_sequence=0,
            availability=availability,
            relation_kind=NewsCanonicalRelationKind.SAME_STORY,
            method=NewsCanonicalizationMethod.EXACT_CANONICAL_URL,
            left_item_revision_sequence=0,
            right_item_revision_sequence=0,
            algorithm_version="fx58_v2",
        )
    )


# --- Section B: canonical membership vs evidence eligibility ----------------


async def test_ineligible_intermediate_member_survives_the_view(
    news_repo: SqlAlchemyNewsRepository,
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
    semantic_repo: SqlAlchemyNewsSemanticRepository,
    get_snapshot: GetPairNewsEvidenceSnapshot,
) -> None:
    """A-SAME-B-SAME-C, B ineligible (quarantined) -- one story entry,
    canonical membership A/B/C, eligible membership A/C, provenance
    includes A-B and B-C, B contributes no detail, and the story's
    own window anchor follows FX-60 (eligible members only), never
    presentation logic."""
    a = await _make_item(news_repo, "secb-a", first_seen_at=_ts(9))
    b = await _make_item(
        news_repo,
        "secb-b",
        first_seen_at=_ts(9, 1),
        evidence_disposition=NewsEvidenceDisposition.QUARANTINED,
    )
    c = await _make_item(news_repo, "secb-c", first_seen_at=_ts(9, 10))
    await _add_relation(canon_repo, a, b, availability=_ts(9, 20))
    await _add_relation(canon_repo, b, c, availability=_ts(9, 25))
    await _add_annotation(semantic_repo, a, availability=_ts(9, 2))
    await _add_annotation(semantic_repo, c, availability=_ts(9, 11))

    snapshot = await get_snapshot(EURUSD, _ts(0), _ts(10))
    view = build_news_evidence_view(snapshot)

    assert view["accounting"]["groups_total"] == 1
    assert len(view["active_entries"]) == 1
    entry = view["active_entries"][0]

    assert set(entry["canonical_member_news_item_keys"]) == {a, b, c}
    assert set(entry["member_news_item_keys"]) == {a, c}
    assert {m["news_item_key"] for m in entry["members"]} == {a, c}
    assert b not in {m["news_item_key"] for m in entry["members"]}

    provenance_pairs = {
        frozenset((r["left_news_item_key"], r["right_news_item_key"]))
        for r in entry["relation_provenance"]
    }
    assert provenance_pairs == {frozenset((a, b)), frozenset((b, c))}

    # Window anchor follows FX-60's own eligible-members-only rule --
    # the view never recomputes this from the full canonical set.
    assert entry["story_first_seen_at"] == _ts(9).value.isoformat()


# --- Section C: historical sequence T1-T4 ------------------------------------


async def test_historical_sequence_t1_to_t4_view_matches_snapshot_at_each_instant(
    news_repo: SqlAlchemyNewsRepository,
    canon_repo: SqlAlchemyNewsCanonicalizationRepository,
    semantic_repo: SqlAlchemyNewsSemanticRepository,
    get_snapshot: GetPairNewsEvidenceSnapshot,
) -> None:
    """T1: item exists, no semantics. T2: CURRENT semantics arrive.
    T3: a second item becomes canonically linked. T4: the first item
    is revised, making its old annotation STALE. The view at each
    historical `as_of` must reflect ONLY what was knowable then."""
    first = await _make_item(news_repo, "secc-first", first_seen_at=_ts(9))

    # T1: no semantics at all yet.
    t1 = _ts(9, 5)
    view_t1 = build_news_evidence_view(await get_snapshot(EURUSD, _ts(0), t1))
    assert view_t1["active_entries"] == []
    assert len(view_t1["semantic_gaps"]) == 1
    assert view_t1["semantic_gaps"][0]["semantic_state"] == "UNCLASSIFIED"

    # T2: CURRENT semantics become available.
    await _add_annotation(semantic_repo, first, availability=_ts(9, 10))
    t2 = _ts(9, 15)
    view_t2 = build_news_evidence_view(await get_snapshot(EURUSD, _ts(0), t2))
    assert len(view_t2["active_entries"]) == 1
    assert view_t2["active_entries"][0]["canonical_member_news_item_keys"] == [first]

    # Re-querying T1 again, AFTER T2's data was added, must be unchanged.
    view_t1_again = build_news_evidence_view(await get_snapshot(EURUSD, _ts(0), t1))
    assert view_t1_again == view_t1

    # T3: a second item becomes canonically linked.
    second = await _make_item(news_repo, "secc-second", first_seen_at=_ts(9, 20))
    await _add_annotation(semantic_repo, second, availability=_ts(9, 21))
    await _add_relation(canon_repo, first, second, availability=_ts(9, 25))
    t3 = _ts(9, 30)
    view_t3 = build_news_evidence_view(await get_snapshot(EURUSD, _ts(0), t3))
    assert len(view_t3["active_entries"]) == 1
    assert set(view_t3["active_entries"][0]["canonical_member_news_item_keys"]) == {first, second}

    # Re-querying T2 again, AFTER T3's relation was added, must be unchanged
    # -- the future relationship must never appear in the earlier snapshot.
    view_t2_again = build_news_evidence_view(await get_snapshot(EURUSD, _ts(0), t2))
    assert view_t2_again == view_t2

    # T4: the first item is revised -- its OLD annotation (basis rev 0)
    # no longer matches the new latest vintage (rev 1), so it becomes STALE.
    await _append_revision(news_repo, first, revision_sequence=1, availability=_ts(9, 40))
    t4 = _ts(9, 45)
    view_t4 = build_news_evidence_view(await get_snapshot(EURUSD, _ts(0), t4))

    # STALE evidence does not retain positive relevance from its old
    # annotation -- the group now has an unresolved semantic gap for
    # `first`, and must not be silently treated as still fully CURRENT.
    gap_keys = {g["news_item_key"] for g in view_t4["semantic_gaps"]}
    assert first in gap_keys
    matching_gaps = [g for g in view_t4["semantic_gaps"] if g["news_item_key"] == first]
    assert matching_gaps[0]["semantic_state"] == "STALE"

    # Re-querying T3 again, AFTER T4's revision, must be unchanged --
    # historical display output remains deterministic after future events.
    view_t3_again = build_news_evidence_view(await get_snapshot(EURUSD, _ts(0), t3))
    assert view_t3_again == view_t3
