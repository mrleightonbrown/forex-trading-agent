"""FX-59 Section 75: `SqlAlchemyNewsSemanticRepository` round-trip,
point-in-time query, FK, and conflict/idempotency tests against live
Postgres.

Requires a live Postgres with the FX-59 migration (`4b2621787a37`)
applied -- run `docker compose up -d db && alembic upgrade head`
first. Uses a dedicated test `source_key` prefix (never a real
source), so genuine rows from any real adapter are never at risk.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.application.ports.news_semantic_repository import (
    NewsSemanticAnnotationConflictError,
)
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
from forex_agent.domain.news_topic import NewsTopic
from forex_agent.domain.news_topic_annotation import NewsTopicAnnotation
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

TEST_SOURCE_KEY = "__fx59_repo_test__"


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
    headline: str = "H",
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


def _classification() -> NewsSemanticClassification:
    return NewsSemanticClassification(
        entities=(
            NewsEntityAnnotation(
                entity_type=NewsEntityType.INSTITUTION,
                entity_key="FEDERAL_RESERVE",
                evidence=(NewsEntityEvidenceKind.SOURCE_PROFILE,),
            ),
        ),
        topics=(
            NewsTopicAnnotation(topic=NewsTopic.MONETARY_POLICY, matched_terms=("bank rate",)),
        ),
        currency_relevance=(
            NewsCurrencyRelevance(
                currency_code="USD", reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,)
            ),
        ),
    )


def _annotation(
    news_item_key: str,
    *,
    revision_sequence: int = 0,
    availability: UtcTimestamp,
    basis_news_item_revision_sequence: int = 0,
    algorithm_version: str = "fx59_v1",
) -> NewsSemanticAnnotationVintage:
    return NewsSemanticAnnotationVintage(
        news_item_key=news_item_key,
        revision_sequence=revision_sequence,
        availability=availability,
        basis_news_item_revision_sequence=basis_news_item_revision_sequence,
        algorithm_version=algorithm_version,
        classification=_classification(),
    )


# --- Round-trip / PIT --------------------------------------------------------


async def test_annotation_round_trip(
    news_repo: SqlAlchemyNewsRepository, semantic_repo: SqlAlchemyNewsSemanticRepository
) -> None:
    item = await _make_item(news_repo, "rt-1", availability=_ts(10))
    annotation = _annotation(item, availability=_ts(11))

    await semantic_repo.add_annotation_vintage(annotation)

    stored = await semantic_repo.list_annotation_vintages_for_item(item)
    assert stored == (annotation,)


async def test_latest_annotation_before_availability_is_none(
    news_repo: SqlAlchemyNewsRepository, semantic_repo: SqlAlchemyNewsSemanticRepository
) -> None:
    item = await _make_item(news_repo, "pit-1", availability=_ts(10))
    annotation = _annotation(item, availability=_ts(11))
    await semantic_repo.add_annotation_vintage(annotation)

    before = await semantic_repo.latest_annotation_as_of(item, _ts(10, 30))
    assert before is None

    at_or_after = await semantic_repo.latest_annotation_as_of(item, _ts(11))
    assert at_or_after == annotation


async def test_equal_availability_higher_revision_wins(
    news_repo: SqlAlchemyNewsRepository, semantic_repo: SqlAlchemyNewsSemanticRepository
) -> None:
    item = await _make_item(news_repo, "tie-1", availability=_ts(10))
    first = _annotation(item, revision_sequence=0, availability=_ts(12))
    await semantic_repo.add_annotation_vintage(first)
    second = _annotation(
        item, revision_sequence=1, availability=_ts(12), basis_news_item_revision_sequence=0
    )
    await semantic_repo.add_annotation_vintage(second)

    latest = await semantic_repo.latest_annotation_as_of(item, _ts(12))
    assert latest is not None
    assert latest.revision_sequence == 1


# --- FK enforcement -----------------------------------------------------------


async def test_fk_rejects_unknown_news_item(
    semantic_repo: SqlAlchemyNewsSemanticRepository,
) -> None:
    annotation = _annotation("does-not-exist", availability=_ts(10))
    with pytest.raises(IntegrityError):
        await semantic_repo.add_annotation_vintage(annotation)


async def test_fk_rejects_unknown_basis_vintage(
    news_repo: SqlAlchemyNewsRepository, semantic_repo: SqlAlchemyNewsSemanticRepository
) -> None:
    item = await _make_item(news_repo, "fk-basis", availability=_ts(10))
    annotation = _annotation(item, availability=_ts(11), basis_news_item_revision_sequence=99)
    with pytest.raises(IntegrityError):
        await semantic_repo.add_annotation_vintage(annotation)


# --- Idempotency / conflict ---------------------------------------------------


async def test_identical_write_is_idempotent(
    news_repo: SqlAlchemyNewsRepository, semantic_repo: SqlAlchemyNewsSemanticRepository
) -> None:
    item = await _make_item(news_repo, "idem-1", availability=_ts(10))
    annotation = _annotation(item, availability=_ts(11))

    first_result = await semantic_repo.add_annotation_vintage(annotation)
    second_result = await semantic_repo.add_annotation_vintage(annotation)

    assert first_result.inserted is True
    assert second_result.inserted is False
    stored = await semantic_repo.list_annotation_vintages_for_item(item)
    assert len(stored) == 1


async def test_conflicting_write_raises(
    news_repo: SqlAlchemyNewsRepository, semantic_repo: SqlAlchemyNewsSemanticRepository
) -> None:
    item = await _make_item(news_repo, "conflict-1", availability=_ts(10))
    original = _annotation(item, availability=_ts(11))
    await semantic_repo.add_annotation_vintage(original)

    # Same identity (revision_sequence=0), but a DIFFERENT availability
    # -- a genuine content mismatch, not an exact duplicate.
    conflicting = _annotation(item, availability=_ts(12))

    with pytest.raises(NewsSemanticAnnotationConflictError):
        await semantic_repo.add_annotation_vintage(conflicting)


# --- No-UPDATE / candidate projection -----------------------------------------


async def test_candidates_as_of_includes_source_key(
    news_repo: SqlAlchemyNewsRepository, semantic_repo: SqlAlchemyNewsSemanticRepository
) -> None:
    item = await _make_item(news_repo, "cand-1", availability=_ts(9))

    candidates = await semantic_repo.list_candidates_as_of(_ts(10))

    matching = [c for c in candidates if c.news_item_key == item]
    assert len(matching) == 1
    assert matching[0].source_key == TEST_SOURCE_KEY
    assert matching[0].basis_news_item_revision_sequence == 0


async def test_list_latest_annotation_states_as_of_one_per_item(
    news_repo: SqlAlchemyNewsRepository, semantic_repo: SqlAlchemyNewsSemanticRepository
) -> None:
    item = await _make_item(news_repo, "states-1", availability=_ts(9))
    first = _annotation(item, revision_sequence=0, availability=_ts(10))
    await semantic_repo.add_annotation_vintage(first)
    second = _annotation(
        item, revision_sequence=1, availability=_ts(11), basis_news_item_revision_sequence=0
    )
    await semantic_repo.add_annotation_vintage(second)

    states = await semantic_repo.list_latest_annotation_states_as_of(_ts(12))
    matching = [s for s in states if s.news_item_key == item]
    assert len(matching) == 1
    assert matching[0].revision_sequence == 1
