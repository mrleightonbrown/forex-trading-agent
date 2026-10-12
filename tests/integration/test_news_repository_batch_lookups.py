"""FX-60H Section H3: proves `SqlAlchemyNewsRepository.latest_
evidence_eligible_vintages_as_of` and `SqlAlchemyNewsSemanticReposi
tory.latest_annotations_as_of` (the new BATCH lookup methods) produce
results byte-identical to calling their own single-item counterparts
once per key -- across `CURRENT`/`STALE`/`UNCLASSIFIED`-shaped data,
multiple revisions, backfill inclusion/exclusion, and historical
`as_of` queries. The single-item methods themselves are completely
UNTOUCHED by this story; this file exists specifically to prove the
NEW batch path is a safe, behavior-preserving optimization, never a
second, independently-maintained selection rule."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.domain.news_currency_relevance import NewsCurrencyRelevance
from forex_agent.domain.news_currency_relevance_reason import NewsCurrencyRelevanceReason
from forex_agent.domain.news_entity_annotation import NewsEntityAnnotation
from forex_agent.domain.news_entity_evidence_kind import NewsEntityEvidenceKind
from forex_agent.domain.news_entity_type import NewsEntityType
from forex_agent.domain.news_evidence_disposition import NewsEvidenceDisposition
from forex_agent.domain.news_item_vintage import NewsItemVintage
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.news_semantic_annotation_vintage import NewsSemanticAnnotationVintage
from forex_agent.domain.news_semantic_classification import NewsSemanticClassification
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

TEST_SOURCE_KEY = "__fx60h_batch_lookup_test__"


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
    observation_mode: NewsObservationMode = NewsObservationMode.PROSPECTIVE,
    evidence_disposition: NewsEvidenceDisposition = NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
) -> str:
    registration = await news_repo._register_source_item_for_test_setup(
        _identity(suffix), availability, observation_mode
    )
    vintage = NewsItemVintage(
        news_item_key=registration.news_item_key,
        revision_sequence=0,
        availability=availability,
        observation_mode=observation_mode,
        headline="H",
        source_channel="test_channel",
        observed_source_channels=("test_channel",),
        source_status=NewsSourceStatus.ACTIVE,
        evidence_disposition=evidence_disposition,
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
    evidence_disposition: NewsEvidenceDisposition = NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
) -> None:
    vintage = NewsItemVintage(
        news_item_key=news_item_key,
        revision_sequence=revision_sequence,
        availability=availability,
        observation_mode=NewsObservationMode.PROSPECTIVE,
        headline="H (updated)",
        source_channel="test_channel",
        observed_source_channels=("test_channel",),
        source_status=NewsSourceStatus.ACTIVE,
        evidence_disposition=evidence_disposition,
    )
    await news_repo.add_vintage(vintage)


def _classification() -> NewsSemanticClassification:
    return NewsSemanticClassification(
        entities=(
            NewsEntityAnnotation(
                entity_type=NewsEntityType.INSTITUTION,
                entity_key="FEDERAL_RESERVE",
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


# --- Vintage batch lookup equivalence ----------------------------------------


async def test_batch_vintage_lookup_matches_single_item_for_mixed_population(
    news_repo: SqlAlchemyNewsRepository,
) -> None:
    eligible = await _make_item(news_repo, "v-eligible", availability=_ts(9))
    quarantined = await _make_item(
        news_repo,
        "v-quarantined",
        availability=_ts(9),
        evidence_disposition=NewsEvidenceDisposition.QUARANTINED,
    )
    backfill_only = await _make_item(
        news_repo,
        "v-backfill",
        availability=_ts(9),
        observation_mode=NewsObservationMode.BACKFILL,
    )
    missing = "v-does-not-exist"
    keys = (eligible, quarantined, backfill_only, missing)

    for include_backfill in (False, True):
        single_item_results = {}
        for key in keys:
            result = await news_repo.latest_evidence_eligible_vintage_as_of(
                key, _ts(10), include_backfill=include_backfill
            )
            if result is not None:
                single_item_results[key] = result

        batch_results = await news_repo.latest_evidence_eligible_vintages_as_of(
            keys, _ts(10), include_backfill=include_backfill
        )

        assert batch_results == single_item_results


async def test_batch_vintage_lookup_matches_single_item_across_revisions(
    news_repo: SqlAlchemyNewsRepository,
) -> None:
    item = await _make_item(news_repo, "v-revisions", availability=_ts(9))
    await _append_revision(news_repo, item, revision_sequence=1, availability=_ts(9, 30))
    await _append_revision(news_repo, item, revision_sequence=2, availability=_ts(10))

    for as_of in (_ts(9, 15), _ts(9, 45), _ts(10, 30)):
        single = await news_repo.latest_evidence_eligible_vintage_as_of(item, as_of)
        batch = await news_repo.latest_evidence_eligible_vintages_as_of((item,), as_of)
        assert batch.get(item) == single


async def test_batch_vintage_lookup_empty_keys_returns_empty_dict(
    news_repo: SqlAlchemyNewsRepository,
) -> None:
    assert await news_repo.latest_evidence_eligible_vintages_as_of((), _ts(10)) == {}


# --- Annotation batch lookup equivalence --------------------------------------


async def test_batch_annotation_lookup_matches_single_item_for_mixed_population(
    news_repo: SqlAlchemyNewsRepository, semantic_repo: SqlAlchemyNewsSemanticRepository
) -> None:
    classified = await _make_item(news_repo, "a-classified", availability=_ts(9))
    await _add_annotation(semantic_repo, classified, availability=_ts(9, 5))
    unclassified = await _make_item(news_repo, "a-unclassified", availability=_ts(9))
    missing = "a-does-not-exist"
    keys = (classified, unclassified, missing)

    single_item_results = {}
    for key in keys:
        result = await semantic_repo.latest_annotation_as_of(key, _ts(10))
        if result is not None:
            single_item_results[key] = result

    batch_results = await semantic_repo.latest_annotations_as_of(keys, _ts(10))

    assert batch_results == single_item_results


async def test_batch_annotation_lookup_matches_single_item_across_historical_instants(
    news_repo: SqlAlchemyNewsRepository, semantic_repo: SqlAlchemyNewsSemanticRepository
) -> None:
    item = await _make_item(news_repo, "a-historical", availability=_ts(9))
    await _add_annotation(semantic_repo, item, availability=_ts(9, 5))
    await _append_revision(news_repo, item, revision_sequence=1, availability=_ts(9, 20))
    await _add_annotation(
        semantic_repo,
        item,
        availability=_ts(9, 30),
        basis_news_item_revision_sequence=1,
        revision_sequence=1,
    )

    for as_of in (_ts(9, 10), _ts(9, 25), _ts(9, 35)):
        single = await semantic_repo.latest_annotation_as_of(item, as_of)
        batch = await semantic_repo.latest_annotations_as_of((item,), as_of)
        assert batch.get(item) == single


async def test_batch_annotation_lookup_empty_keys_returns_empty_dict(
    semantic_repo: SqlAlchemyNewsSemanticRepository,
) -> None:
    assert await semantic_repo.latest_annotations_as_of((), _ts(10)) == {}
