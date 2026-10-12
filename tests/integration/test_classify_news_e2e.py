"""FX-59: full-chain Postgres end-to-end tests for `ClassifyNewsOnce`
+ `RecordNewsSemanticAnnotation` + `GetNewsSemanticStateAsOf` --
including the two MANDATORY PIT regressions this story's own Section
76/77 call for: the stale-state worked example, and the algorithm-
version PIT example.

Requires a live Postgres with the FX-59 migration (`4b2621787a37`)
applied. Uses a dedicated test `source_key` that IS one of the real
registered semantic source profiles (`"FED"`) -- deliberately, since
`classify_news_semantics` fails closed for any unregistered source --
but a dedicated, never-real `external_item_id` prefix, so real Fed
rows are never at risk.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.application.use_cases.classify_news_once import ClassifyNewsOnce
from forex_agent.application.use_cases.get_news_semantic_state_as_of import (
    GetNewsSemanticStateAsOf,
    NewsSemanticState,
)
from forex_agent.application.use_cases.record_news_semantic_annotation import (
    RecordNewsSemanticAnnotation,
)
from forex_agent.domain.news_evidence_disposition import NewsEvidenceDisposition
from forex_agent.domain.news_item_vintage import NewsItemVintage
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.news_semantic_classifying import (
    NewsSemanticClassificationCandidate,
    classify_news_semantics,
)
from forex_agent.domain.news_source_identity import NewsSourceIdentity
from forex_agent.domain.news_source_status import NewsSourceStatus
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.models.news_item import NewsItemRow
from forex_agent.infrastructure.db.models.news_item_vintage import NewsItemVintageRow
from forex_agent.infrastructure.db.models.news_semantic_annotation_vintage import (
    NewsSemanticAnnotationVintageRow,
)
from forex_agent.infrastructure.db.models.news_source_mapping import NewsSourceMappingRow
from forex_agent.infrastructure.db.news_repository import SqlAlchemyNewsRepository
from forex_agent.infrastructure.db.news_semantic_repository import SqlAlchemyNewsSemanticRepository
from forex_agent.infrastructure.db.session import get_engine

TEST_SOURCE_KEY = "FED"
TEST_EXTERNAL_ID_PREFIX = "__fx59_e2e_test__"


def _ts(hour: int, minute: int = 0, second: int = 0) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, hour, minute, second, tzinfo=UTC))


def _identity(suffix: str) -> NewsSourceIdentity:
    return NewsSourceIdentity(
        source_key=TEST_SOURCE_KEY, external_item_id=f"{TEST_EXTERNAL_ID_PREFIX}{suffix}"
    )


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
                    .where(
                        NewsSourceMappingRow.external_item_id.startswith(TEST_EXTERNAL_ID_PREFIX)
                    )
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
def semantic_repo(
    session: AsyncSession, news_repo: SqlAlchemyNewsRepository
) -> SqlAlchemyNewsSemanticRepository:
    return SqlAlchemyNewsSemanticRepository(session, news_repo)


async def _make_item(
    news_repo: SqlAlchemyNewsRepository,
    suffix: str,
    *,
    availability: UtcTimestamp,
    headline: str = "The Federal Reserve met today.",
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
    )
    await news_repo.add_vintage(vintage)
    return registration.news_item_key


async def _append_revision(
    news_repo: SqlAlchemyNewsRepository,
    news_item_key: str,
    *,
    revision_sequence: int,
    availability: UtcTimestamp,
    headline: str,
) -> None:
    vintage = NewsItemVintage(
        news_item_key=news_item_key,
        revision_sequence=revision_sequence,
        availability=availability,
        observation_mode=NewsObservationMode.PROSPECTIVE,
        headline=headline,
        source_channel="test_channel",
        observed_source_channels=("test_channel",),
        source_status=NewsSourceStatus.ACTIVE,
        evidence_disposition=NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
    )
    await news_repo.add_vintage(vintage)


# --- Full chain ---------------------------------------------------------
#
# `ClassifyNewsOnce.list_candidates_as_of` has no source-key filter --
# it considers EVERY evidence-eligible NewsItem, including the real
# genuine rows already in this dev database (unlike FX-58's own
# canonicalizer, which only WRITES on an actual pair match, FX-59's
# classifier writes one annotation per item unconditionally). Running
# write-mode here would therefore perform FX-59's own real production
# write (Section 83) as an unreviewed side effect of running the test
# suite -- bypassing this story's own mandatory pre-persistence dry-
# run safety gate (Section 79/80). These two tests therefore use
# `dry_run=True` deliberately: proving the full read/classify chain
# works correctly against real Postgres, with zero persistence risk.
# Real persistence is proven separately, scoped to one test item at a
# time, by `test_news_semantic_repository.py` and by the direct
# `record(...)` calls in the two PIT tests below.


async def test_classify_once_full_chain_through_real_postgres(
    news_repo: SqlAlchemyNewsRepository, semantic_repo: SqlAlchemyNewsSemanticRepository
) -> None:
    item = await _make_item(
        news_repo, "chain-1", availability=_ts(9), headline="Monetary policy decision today."
    )
    record = RecordNewsSemanticAnnotation(semantic_repo)
    classify = ClassifyNewsOnce(semantic_repo, record, clock=lambda: _ts(10))

    result = await classify(dry_run=True)

    matching = [d for d in result.diagnostics if d.news_item_key == item]
    assert len(matching) == 1
    assert "MONETARY_POLICY" in {t.value for t in matching[0].topics}

    stored = await semantic_repo.list_annotation_vintages_for_item(item)
    assert stored == ()


async def test_classify_once_never_mutates_source_news_items(
    news_repo: SqlAlchemyNewsRepository, semantic_repo: SqlAlchemyNewsSemanticRepository
) -> None:
    item = await _make_item(news_repo, "no-mutate-1", availability=_ts(9))
    before = await news_repo.list_vintages(item)

    record = RecordNewsSemanticAnnotation(semantic_repo)
    classify = ClassifyNewsOnce(semantic_repo, record, clock=lambda: _ts(10))
    await classify(dry_run=True)

    after = await news_repo.list_vintages(item)
    assert before == after


# --- Section 76: the MANDATORY stale-state worked example --------------------


async def test_stale_state_worked_example(
    news_repo: SqlAlchemyNewsRepository, semantic_repo: SqlAlchemyNewsSemanticRepository
) -> None:
    item = await _make_item(news_repo, "stale-1", availability=_ts(9))
    record = RecordNewsSemanticAnnotation(semantic_repo)
    get_state = GetNewsSemanticStateAsOf(semantic_repo, news_repo)

    # 09:05: classify rev0 -- CURRENT.
    candidate = NewsSemanticClassificationCandidate(
        news_item_key=item,
        source_key=TEST_SOURCE_KEY,
        basis_news_item_revision_sequence=0,
        basis_availability=_ts(9),
        headline="The Federal Reserve met today.",
        summary=None,
        body_text=None,
        source_content_type=None,
        source_channel=None,
    )
    result_0905 = await record(
        item,
        0,
        availability=_ts(9, 5),
        classification=classify_news_semantics(candidate),
        algorithm_version="fx59_v1",
    )
    assert result_0905.annotation.revision_sequence == 0

    state_at_0910 = await get_state(item, _ts(9, 10))
    assert state_at_0910.state is NewsSemanticState.CURRENT

    # 09:20: a NEW rev1 becomes evidence-eligible.
    await _append_revision(
        news_repo,
        item,
        revision_sequence=1,
        availability=_ts(9, 20),
        headline="The Federal Reserve met today (updated).",
    )

    # 09:25: classifier has NOT re-run -- STALE.
    state_at_0925 = await get_state(item, _ts(9, 25))
    assert state_at_0925.state is NewsSemanticState.STALE

    # 09:30: classifier re-runs against rev1.
    rev1_candidate = NewsSemanticClassificationCandidate(
        news_item_key=item,
        source_key=TEST_SOURCE_KEY,
        basis_news_item_revision_sequence=1,
        basis_availability=_ts(9, 20),
        headline="The Federal Reserve met today (updated).",
        summary=None,
        body_text=None,
        source_content_type=None,
        source_channel=None,
    )
    result_0930 = await record(
        item,
        1,
        availability=_ts(9, 30),
        classification=classify_news_semantics(rev1_candidate),
        algorithm_version="fx59_v1",
    )
    assert result_0930.annotation.revision_sequence == 1

    # 09:35: now CURRENT again.
    state_at_0935 = await get_state(item, _ts(9, 35))
    assert state_at_0935.state is NewsSemanticState.CURRENT

    # Historical query before rev1 ever existed: the rev0 annotation
    # remains CURRENT for that historical instant -- no destructive
    # rewrite.
    historical_state = await get_state(item, _ts(9, 10))
    assert historical_state.state is NewsSemanticState.CURRENT
    assert historical_state.annotation is not None
    assert historical_state.annotation.revision_sequence == 0


# --- Section 77: the MANDATORY algorithm-version PIT example -----------------


async def test_algorithm_version_pit_example(
    news_repo: SqlAlchemyNewsRepository, semantic_repo: SqlAlchemyNewsSemanticRepository
) -> None:
    item = await _make_item(news_repo, "algver-1", availability=_ts(9))
    record = RecordNewsSemanticAnnotation(semantic_repo)
    get_state = GetNewsSemanticStateAsOf(semantic_repo, news_repo)

    candidate = NewsSemanticClassificationCandidate(
        news_item_key=item,
        source_key=TEST_SOURCE_KEY,
        basis_news_item_revision_sequence=0,
        basis_availability=_ts(9),
        headline="The Federal Reserve met today.",
        summary=None,
        body_text=None,
        source_content_type=None,
        source_channel=None,
    )
    classification = classify_news_semantics(candidate)

    # v1 annotation at T1 = 10:00.
    await record(
        item, 0, availability=_ts(10), classification=classification, algorithm_version="fx59_v1"
    )

    # v2 "reclassification" of the SAME basis at T2 = 11:00 (same
    # output here, but under a genuinely different algorithm_version
    # -- this is explicitly permitted, Section 54).
    await record(
        item, 0, availability=_ts(11), classification=classification, algorithm_version="fx59_v2"
    )

    as_of_between = await semantic_repo.latest_annotation_as_of(item, _ts(10, 30))
    assert as_of_between is not None
    assert as_of_between.algorithm_version == "fx59_v1"

    as_of_after = await semantic_repo.latest_annotation_as_of(item, _ts(11))
    assert as_of_after is not None
    assert as_of_after.algorithm_version == "fx59_v2"

    # No rewrite -- both revisions coexist.
    all_vintages = await semantic_repo.list_annotation_vintages_for_item(item)
    assert len(all_vintages) == 2

    state_at_1030 = await get_state(item, _ts(10, 30))
    assert state_at_1030.state is NewsSemanticState.CURRENT
    assert state_at_1030.annotation is not None
    assert state_at_1030.annotation.algorithm_version == "fx59_v1"
