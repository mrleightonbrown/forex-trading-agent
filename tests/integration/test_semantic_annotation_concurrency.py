"""FX-59 Section 61/62: concurrent-write safety through `RecordNews
SemanticAnnotation` itself -- not merely the repository's own `add_
annotation_vintage` in isolation (already covered by `test_news_
semantic_repository.py::test_identical_write_is_idempotent`). Mirrors
FX-58H's own `test_canonical_relation_concurrency.py` precedent
exactly: two REAL, independent Postgres sessions racing through the
use case, via `asyncio.gather`.

Requires a live Postgres with migration `4b2621787a37` applied (the
current head)."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.application.ports.news_semantic_repository import (
    NewsSemanticAnnotationConflictError,
)
from forex_agent.application.use_cases.record_news_semantic_annotation import (
    NewsSemanticAnnotationOutcome,
    RecordNewsSemanticAnnotation,
)
from forex_agent.domain.news_currency_relevance import NewsCurrencyRelevance
from forex_agent.domain.news_currency_relevance_reason import NewsCurrencyRelevanceReason
from forex_agent.domain.news_entity_annotation import NewsEntityAnnotation
from forex_agent.domain.news_entity_evidence_kind import NewsEntityEvidenceKind
from forex_agent.domain.news_entity_type import NewsEntityType
from forex_agent.domain.news_evidence_disposition import NewsEvidenceDisposition
from forex_agent.domain.news_item_vintage import NewsItemVintage
from forex_agent.domain.news_observation_mode import NewsObservationMode
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

TEST_SOURCE_KEY = "__fx59_concurrency_test__"
# `ClassifyNewsOnce`'s own classify-count-under-a-race test must go
# through `classify_news_semantics`, which fails closed for any
# unregistered source -- so that ONE test's item deliberately uses a
# REAL registered source_key ("FED"), distinguished by a dedicated,
# never-real `external_item_id` prefix (mirrors `test_classify_news_
# e2e.py`'s own precaution).
CLASSIFY_SOURCE_KEY = "FED"
CLASSIFY_EXTERNAL_ID_PREFIX = "__fx59_concurrency_classify_test__"


def _ts(hour: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, hour, tzinfo=UTC))


def _identity(suffix: str) -> NewsSourceIdentity:
    return NewsSourceIdentity(source_key=TEST_SOURCE_KEY, external_item_id=suffix)


def _classify_identity(suffix: str) -> NewsSourceIdentity:
    return NewsSourceIdentity(
        source_key=CLASSIFY_SOURCE_KEY, external_item_id=f"{CLASSIFY_EXTERNAL_ID_PREFIX}{suffix}"
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
                    .where(NewsSourceMappingRow.source_key == TEST_SOURCE_KEY)
                    .returning(NewsSourceMappingRow.news_item_key)
                )
            )
            .scalars()
            .all()
        )
        classify_item_keys = (
            (
                await cleanup_session.execute(
                    delete(NewsSourceMappingRow)
                    .where(
                        NewsSourceMappingRow.external_item_id.startswith(
                            CLASSIFY_EXTERNAL_ID_PREFIX
                        )
                    )
                    .returning(NewsSourceMappingRow.news_item_key)
                )
            )
            .scalars()
            .all()
        )
        for key in (*item_keys, *classify_item_keys):
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


async def _make_item(
    news_repo: SqlAlchemyNewsRepository, suffix: str, *, for_classification: bool = False
) -> str:
    identity = _classify_identity(suffix) if for_classification else _identity(suffix)
    registration = await news_repo._register_source_item_for_test_setup(
        identity, _ts(9), NewsObservationMode.PROSPECTIVE
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
    )
    await news_repo.add_vintage(vintage)
    return registration.news_item_key


def _classification(currency: str = "USD") -> NewsSemanticClassification:
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
                currency_code=currency, reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,)
            ),
        ),
    )


# --- Section 61: identical concurrent FIRST classification -----------------


@pytest.mark.asyncio
async def test_concurrent_identical_first_classification_one_created_one_unchanged(
    news_repo: SqlAlchemyNewsRepository,
) -> None:
    item = await _make_item(news_repo, "ident-1")

    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)

    async def _record() -> NewsSemanticAnnotationOutcome:
        async with session_factory() as own_session:
            own_news_repo = SqlAlchemyNewsRepository(own_session)
            own_semantic_repo = SqlAlchemyNewsSemanticRepository(own_session, own_news_repo)
            record = RecordNewsSemanticAnnotation(own_semantic_repo)
            result = await record(
                item,
                0,
                availability=_ts(10),
                classification=_classification(),
                algorithm_version="fx59_v1",
            )
            return result.outcome

    outcomes = await asyncio.gather(_record(), _record())
    assert sorted(o.value for o in outcomes) == sorted(
        [NewsSemanticAnnotationOutcome.CREATED.value, NewsSemanticAnnotationOutcome.UNCHANGED.value]
    )

    async with session_factory() as check_session:
        check_news_repo = SqlAlchemyNewsRepository(check_session)
        check_semantic_repo = SqlAlchemyNewsSemanticRepository(check_session, check_news_repo)
        stored = await check_semantic_repo.list_annotation_vintages_for_item(item)
        assert len(stored) == 1


# --- Section 62: concurrent DIFFERENT payloads for the same new identity ---


@pytest.mark.asyncio
async def test_concurrent_different_payloads_one_wins_one_raises(
    news_repo: SqlAlchemyNewsRepository,
) -> None:
    item = await _make_item(news_repo, "diff-1")

    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)

    async def _record(currency: str) -> str:
        async with session_factory() as own_session:
            own_news_repo = SqlAlchemyNewsRepository(own_session)
            own_semantic_repo = SqlAlchemyNewsSemanticRepository(own_session, own_news_repo)
            record = RecordNewsSemanticAnnotation(own_semantic_repo)
            try:
                result = await record(
                    item,
                    0,
                    availability=_ts(10),
                    classification=_classification(currency),
                    algorithm_version="fx59_v1",
                )
                return result.outcome.value
            except NewsSemanticAnnotationConflictError:
                return "CONFLICT"

    results = await asyncio.gather(_record("USD"), _record("CAD"))

    # Exactly one side wins (CREATED); the other raises a conflict --
    # no silent winner selection, no second revision manufactured.
    assert sorted(results) == sorted([NewsSemanticAnnotationOutcome.CREATED.value, "CONFLICT"])

    async with session_factory() as check_session:
        check_news_repo = SqlAlchemyNewsRepository(check_session)
        check_semantic_repo = SqlAlchemyNewsSemanticRepository(check_session, check_news_repo)
        stored = await check_semantic_repo.list_annotation_vintages_for_item(item)
        assert len(stored) == 1


# --- Section 21: ClassifyNewsOnce's own counter accuracy under a race ------


class _ScopedNewsSemanticRepository:
    """Implements the full `NewsSemanticRepository` Protocol,
    delegating every method to a REAL repository EXCEPT `list_
    candidates_as_of`, which returns a fixed, pre-scoped tuple --
    proves `ClassifyNewsOnce`'s own counter accuracy under a real
    write race without scanning/classifying the rest of this shared
    dev database's genuine production rows (mirrors this story's own
    e2e-test precaution, `test_classify_news_e2e.py`'s own module
    docstring)."""

    def __init__(
        self,
        delegate: SqlAlchemyNewsSemanticRepository,
        scoped_candidates: tuple[object, ...],
    ) -> None:
        self._delegate = delegate
        self._scoped_candidates = scoped_candidates

    async def list_candidates_as_of(
        self, as_of: UtcTimestamp, *, include_backfill: bool = False
    ) -> tuple[object, ...]:
        return self._scoped_candidates

    async def latest_annotation_for_item(self, news_item_key: str) -> object:
        return await self._delegate.latest_annotation_for_item(news_item_key)

    async def latest_annotation_as_of(self, news_item_key: str, as_of: UtcTimestamp) -> object:
        return await self._delegate.latest_annotation_as_of(news_item_key, as_of)

    async def list_annotation_vintages_for_item(self, news_item_key: str) -> object:
        return await self._delegate.list_annotation_vintages_for_item(news_item_key)

    async def list_latest_annotation_states_as_of(self, as_of: UtcTimestamp) -> object:
        return await self._delegate.list_latest_annotation_states_as_of(as_of)

    async def add_annotation_vintage(self, vintage: object) -> object:
        return await self._delegate.add_annotation_vintage(vintage)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_classify_once_annotations_created_reflects_actual_durable_creation(
    news_repo: SqlAlchemyNewsRepository,
) -> None:
    from forex_agent.application.use_cases.classify_news_once import ClassifyNewsOnce

    item = await _make_item(news_repo, "run-1", for_classification=True)

    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)

    async def _run() -> int:
        async with session_factory() as own_session:
            own_news_repo = SqlAlchemyNewsRepository(own_session)
            own_semantic_repo = SqlAlchemyNewsSemanticRepository(own_session, own_news_repo)
            candidates = await own_semantic_repo.list_candidates_as_of(_ts(11))
            scoped_candidates = tuple(c for c in candidates if c.news_item_key == item)
            scoped_repo = _ScopedNewsSemanticRepository(own_semantic_repo, scoped_candidates)
            record = RecordNewsSemanticAnnotation(scoped_repo)  # type: ignore[arg-type]
            classify = ClassifyNewsOnce(scoped_repo, record, clock=lambda: _ts(11))  # type: ignore[arg-type]
            result = await classify()
            return result.annotations_created

    created_counts = await asyncio.gather(_run(), _run())

    # Exactly one of the two concurrent full runs may durably report
    # having created the annotation; the other must report 0 (not
    # fabricate a second revision to "catch up").
    assert sorted(created_counts) == [0, 1]

    async with session_factory() as check_session:
        check_news_repo = SqlAlchemyNewsRepository(check_session)
        check_semantic_repo = SqlAlchemyNewsSemanticRepository(check_session, check_news_repo)
        stored = await check_semantic_repo.list_annotation_vintages_for_item(item)
        assert len(stored) == 1
