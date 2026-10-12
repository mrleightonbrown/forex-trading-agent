"""FX-59 Section 11/66: fast, DB-free unit tests for `GetNewsSemantic
StateAsOf`/`GetNewsSemanticStatesAsOf` against in-memory fakes --
complements the live-Postgres stale-state PIT test in `tests/
integration/test_classify_news_e2e.py`."""

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from forex_agent.application.ports.news_repository import (
    FirstObservationResult,
    NewsVintageWriteOutcome,
)
from forex_agent.application.ports.news_semantic_repository import SemanticAnnotationWriteResult
from forex_agent.application.use_cases.get_news_semantic_state_as_of import (
    GetNewsSemanticStateAsOf,
    GetNewsSemanticStatesAsOf,
    NewsSemanticState,
)
from forex_agent.domain.news_currency_relevance import NewsCurrencyRelevance
from forex_agent.domain.news_currency_relevance_reason import NewsCurrencyRelevanceReason
from forex_agent.domain.news_entity_annotation import NewsEntityAnnotation
from forex_agent.domain.news_entity_evidence_kind import NewsEntityEvidenceKind
from forex_agent.domain.news_entity_type import NewsEntityType
from forex_agent.domain.news_evidence_disposition import NewsEvidenceDisposition
from forex_agent.domain.news_item import NewsItem
from forex_agent.domain.news_item_vintage import NewsItemVintage
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.news_semantic_annotation_vintage import NewsSemanticAnnotationVintage
from forex_agent.domain.news_semantic_classification import NewsSemanticClassification
from forex_agent.domain.news_semantic_classifying import NewsSemanticClassificationCandidate
from forex_agent.domain.news_source_identity import NewsSourceIdentity
from forex_agent.domain.news_source_status import NewsSourceStatus
from forex_agent.domain.timestamps import UtcTimestamp


def _ts(hour: int, minute: int = 0) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, hour, minute, tzinfo=UTC))


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


def _vintage(
    news_item_key: str, revision_sequence: int, availability: UtcTimestamp
) -> NewsItemVintage:
    return NewsItemVintage(
        news_item_key=news_item_key,
        revision_sequence=revision_sequence,
        availability=availability,
        observation_mode=NewsObservationMode.PROSPECTIVE,
        headline="H",
        source_channel="c",
        observed_source_channels=("c",),
        source_status=NewsSourceStatus.ACTIVE,
        evidence_disposition=NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
    )


class FakeNewsRepository:
    """Implements the full `NewsRepository` Protocol -- `GetNewsSema
    nticStateAsOf` itself only ever calls `latest_evidence_eligible_
    vintage_as_of`, but every method is implemented with its EXACT
    Protocol signature so this fake structurally satisfies it (mirrors
    `FakeNewsCanonicalizationRepository`'s own precedent)."""

    def __init__(self, vintages: tuple[NewsItemVintage, ...]) -> None:
        self._vintages = vintages

    async def register_source_item_with_first_vintage(
        self,
        identity: NewsSourceIdentity,
        observed_at: UtcTimestamp,
        observation_mode: NewsObservationMode,
        build_vintage: Callable[[str], NewsItemVintage],
    ) -> FirstObservationResult:
        raise NotImplementedError("not used by GetNewsSemanticStateAsOf")

    async def get_item(self, news_item_key: str) -> NewsItem | None:
        raise NotImplementedError("not used by GetNewsSemanticStateAsOf")

    async def get_item_by_source_identity(self, identity: NewsSourceIdentity) -> NewsItem | None:
        raise NotImplementedError("not used by GetNewsSemanticStateAsOf")

    async def add_vintage(self, vintage: NewsItemVintage) -> NewsVintageWriteOutcome:
        raise NotImplementedError("not used by GetNewsSemanticStateAsOf")

    async def list_vintages(self, news_item_key: str) -> tuple[NewsItemVintage, ...]:
        raise NotImplementedError("not used by GetNewsSemanticStateAsOf")

    async def latest_vintage_as_of(
        self, news_item_key: str, as_of: UtcTimestamp
    ) -> NewsItemVintage | None:
        raise NotImplementedError("not used by GetNewsSemanticStateAsOf")

    async def latest_evidence_eligible_vintage_as_of(
        self, news_item_key: str, as_of: UtcTimestamp, *, include_backfill: bool = False
    ) -> NewsItemVintage | None:
        qualifying = [
            v
            for v in self._vintages
            if v.news_item_key == news_item_key and v.availability.value <= as_of.value
        ]
        if not qualifying:
            return None
        return max(qualifying, key=lambda v: v.revision_sequence)


class FakeNewsSemanticRepository:
    """Implements the full `NewsSemanticRepository` Protocol -- `Get
    NewsSemanticStateAsOf` itself only ever calls `latest_annotation_
    as_of`."""

    def __init__(self, annotations: tuple[NewsSemanticAnnotationVintage, ...]) -> None:
        self._annotations = annotations

    async def list_candidates_as_of(
        self, as_of: UtcTimestamp, *, include_backfill: bool = False
    ) -> tuple[NewsSemanticClassificationCandidate, ...]:
        raise NotImplementedError("not used by GetNewsSemanticStateAsOf")

    async def latest_annotation_for_item(
        self, news_item_key: str
    ) -> NewsSemanticAnnotationVintage | None:
        raise NotImplementedError("not used by GetNewsSemanticStateAsOf")

    async def latest_annotation_as_of(
        self, news_item_key: str, as_of: UtcTimestamp
    ) -> NewsSemanticAnnotationVintage | None:
        qualifying = [
            a
            for a in self._annotations
            if a.news_item_key == news_item_key and a.availability.value <= as_of.value
        ]
        if not qualifying:
            return None
        return max(qualifying, key=lambda a: (a.availability.value, a.revision_sequence))

    async def list_annotation_vintages_for_item(
        self, news_item_key: str
    ) -> tuple[NewsSemanticAnnotationVintage, ...]:
        raise NotImplementedError("not used by GetNewsSemanticStateAsOf")

    async def list_latest_annotation_states_as_of(
        self, as_of: UtcTimestamp
    ) -> tuple[NewsSemanticAnnotationVintage, ...]:
        raise NotImplementedError("not used by GetNewsSemanticStateAsOf")

    async def add_annotation_vintage(
        self, vintage: NewsSemanticAnnotationVintage
    ) -> SemanticAnnotationWriteResult:
        raise NotImplementedError("not used by GetNewsSemanticStateAsOf")


@pytest.mark.asyncio
async def test_unclassified_when_no_annotation_exists() -> None:
    news_repo = FakeNewsRepository((_vintage("K1", 0, _ts(9)),))
    semantic_repo = FakeNewsSemanticRepository(())
    query = GetNewsSemanticStateAsOf(semantic_repo, news_repo)

    result = await query("K1", _ts(10))

    assert result.state is NewsSemanticState.UNCLASSIFIED
    assert result.annotation is None


@pytest.mark.asyncio
async def test_current_when_basis_matches_latest_eligible_vintage() -> None:
    news_repo = FakeNewsRepository((_vintage("K1", 0, _ts(9)),))
    annotation = NewsSemanticAnnotationVintage(
        news_item_key="K1",
        revision_sequence=0,
        availability=_ts(9, 5),
        basis_news_item_revision_sequence=0,
        algorithm_version="fx59_v1",
        classification=_classification(),
    )
    semantic_repo = FakeNewsSemanticRepository((annotation,))
    query = GetNewsSemanticStateAsOf(semantic_repo, news_repo)

    result = await query("K1", _ts(10))

    assert result.state is NewsSemanticState.CURRENT
    assert result.annotation is annotation


@pytest.mark.asyncio
async def test_stale_when_basis_does_not_match_current_eligible_vintage() -> None:
    # Basis is rev0; a NEW rev1 has since become evidence-eligible,
    # but the classifier has not yet re-run.
    news_repo = FakeNewsRepository((_vintage("K1", 0, _ts(9)), _vintage("K1", 1, _ts(9, 20))))
    annotation = NewsSemanticAnnotationVintage(
        news_item_key="K1",
        revision_sequence=0,
        availability=_ts(9, 5),
        basis_news_item_revision_sequence=0,
        algorithm_version="fx59_v1",
        classification=_classification(),
    )
    semantic_repo = FakeNewsSemanticRepository((annotation,))
    query = GetNewsSemanticStateAsOf(semantic_repo, news_repo)

    result = await query("K1", _ts(9, 25))

    assert result.state is NewsSemanticState.STALE
    assert result.annotation is annotation


@pytest.mark.asyncio
async def test_historical_query_before_the_new_vintage_remains_current() -> None:
    news_repo = FakeNewsRepository((_vintage("K1", 0, _ts(9)), _vintage("K1", 1, _ts(9, 20))))
    annotation = NewsSemanticAnnotationVintage(
        news_item_key="K1",
        revision_sequence=0,
        availability=_ts(9, 5),
        basis_news_item_revision_sequence=0,
        algorithm_version="fx59_v1",
        classification=_classification(),
    )
    semantic_repo = FakeNewsSemanticRepository((annotation,))
    query = GetNewsSemanticStateAsOf(semantic_repo, news_repo)

    result = await query("K1", _ts(9, 10))

    assert result.state is NewsSemanticState.CURRENT


@pytest.mark.asyncio
async def test_batch_variant_reuses_single_item_logic() -> None:
    news_repo = FakeNewsRepository((_vintage("K1", 0, _ts(9)), _vintage("K2", 0, _ts(9))))
    annotation = NewsSemanticAnnotationVintage(
        news_item_key="K1",
        revision_sequence=0,
        availability=_ts(9, 5),
        basis_news_item_revision_sequence=0,
        algorithm_version="fx59_v1",
        classification=_classification(),
    )
    semantic_repo = FakeNewsSemanticRepository((annotation,))
    batch_query = GetNewsSemanticStatesAsOf(semantic_repo, news_repo)

    results = await batch_query(("K1", "K2"), _ts(10))

    states = {r.news_item_key: r.state for r in results}
    assert states == {"K1": NewsSemanticState.CURRENT, "K2": NewsSemanticState.UNCLASSIFIED}
