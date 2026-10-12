"""FX-59: fast, DB-free unit tests for `ClassifyNewsOnce` against an
in-memory fake repository -- complements the live-Postgres end-to-end
suite in `tests/integration/test_classify_news_e2e.py`."""

from datetime import UTC, datetime

import pytest

from forex_agent.application.ports.news_semantic_repository import SemanticAnnotationWriteResult
from forex_agent.application.use_cases.classify_news_once import ClassifyNewsOnce
from forex_agent.application.use_cases.record_news_semantic_annotation import (
    RecordNewsSemanticAnnotation,
)
from forex_agent.domain.news_semantic_annotation_vintage import NewsSemanticAnnotationVintage
from forex_agent.domain.news_semantic_classifying import NewsSemanticClassificationCandidate
from forex_agent.domain.news_semantic_source_profile import UnsupportedNewsSemanticSourceError
from forex_agent.domain.news_topic import NewsTopic
from forex_agent.domain.timestamps import UtcTimestamp


class FakeNewsSemanticRepository:
    def __init__(self, candidates: tuple[NewsSemanticClassificationCandidate, ...]) -> None:
        self._candidates = candidates
        self._annotations: dict[str, list[NewsSemanticAnnotationVintage]] = {}

    async def list_candidates_as_of(
        self, as_of: UtcTimestamp, *, include_backfill: bool = False
    ) -> tuple[NewsSemanticClassificationCandidate, ...]:
        return self._candidates

    async def latest_annotation_for_item(
        self, news_item_key: str
    ) -> NewsSemanticAnnotationVintage | None:
        rows = self._annotations.get(news_item_key, [])
        if not rows:
            return None
        return max(rows, key=lambda r: (r.availability.value, r.revision_sequence))

    async def latest_annotation_as_of(
        self, news_item_key: str, as_of: UtcTimestamp
    ) -> NewsSemanticAnnotationVintage | None:
        raise NotImplementedError

    async def list_annotation_vintages_for_item(
        self, news_item_key: str
    ) -> tuple[NewsSemanticAnnotationVintage, ...]:
        return tuple(self._annotations.get(news_item_key, []))

    async def list_latest_annotation_states_as_of(
        self, as_of: UtcTimestamp
    ) -> tuple[NewsSemanticAnnotationVintage, ...]:
        raise NotImplementedError

    async def add_annotation_vintage(
        self, vintage: NewsSemanticAnnotationVintage
    ) -> SemanticAnnotationWriteResult:
        rows = self._annotations.setdefault(vintage.news_item_key, [])
        rows.append(vintage)
        return SemanticAnnotationWriteResult(inserted=True)


def _ts(hour: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, hour, tzinfo=UTC))


def _candidate(
    news_item_key: str,
    source_key: str,
    headline: str,
    summary: str | None = None,
    body_text: str | None = None,
) -> NewsSemanticClassificationCandidate:
    return NewsSemanticClassificationCandidate(
        news_item_key=news_item_key,
        source_key=source_key,
        basis_news_item_revision_sequence=0,
        basis_availability=_ts(9),
        headline=headline,
        summary=summary,
        body_text=body_text,
        source_content_type=None,
        source_channel=None,
    )


@pytest.mark.asyncio
async def test_clock_captured_exactly_once() -> None:
    calls = []

    def clock() -> UtcTimestamp:
        calls.append(1)
        return _ts(10)

    repo = FakeNewsSemanticRepository((_candidate("K1", "FED", "Routine update."),))
    record = RecordNewsSemanticAnnotation(repo)
    classify = ClassifyNewsOnce(repo, record, clock=clock)

    result = await classify()

    assert len(calls) == 1
    assert result.run_at == _ts(10)


@pytest.mark.asyncio
async def test_deterministic_order_independent_of_input_order() -> None:
    repo = FakeNewsSemanticRepository(
        (
            _candidate("Z1", "FED", "Second item."),
            _candidate("A1", "FED", "First item."),
        )
    )
    record = RecordNewsSemanticAnnotation(repo)
    classify = ClassifyNewsOnce(repo, record, clock=lambda: _ts(10))

    result = await classify()

    assert [d.news_item_key for d in result.diagnostics] == ["A1", "Z1"]


@pytest.mark.asyncio
async def test_dry_run_persists_nothing() -> None:
    repo = FakeNewsSemanticRepository((_candidate("K1", "FED", "Routine update."),))
    record = RecordNewsSemanticAnnotation(repo)
    classify = ClassifyNewsOnce(repo, record, clock=lambda: _ts(10))

    result = await classify(dry_run=True)

    assert result.annotations_created == 1
    stored = await repo.list_annotation_vintages_for_item("K1")
    assert stored == ()


@pytest.mark.asyncio
async def test_write_mode_persists() -> None:
    repo = FakeNewsSemanticRepository((_candidate("K1", "FED", "Routine update."),))
    record = RecordNewsSemanticAnnotation(repo)
    classify = ClassifyNewsOnce(repo, record, clock=lambda: _ts(10))

    await classify(dry_run=False)

    stored = await repo.list_annotation_vintages_for_item("K1")
    assert len(stored) == 1


@pytest.mark.asyncio
async def test_second_run_with_unchanged_data_is_fully_unchanged() -> None:
    repo = FakeNewsSemanticRepository((_candidate("K1", "FED", "Routine update."),))
    record = RecordNewsSemanticAnnotation(repo)
    classify = ClassifyNewsOnce(repo, record, clock=lambda: _ts(10))

    await classify()
    second = await classify()

    assert second.annotations_created == 0
    assert second.unchanged == 1


@pytest.mark.asyncio
async def test_unsupported_source_raises_before_persisting_anything() -> None:
    repo = FakeNewsSemanticRepository(
        (
            _candidate("A1", "FED", "A valid item."),
            _candidate("Z1", "NOT_A_REAL_SOURCE", "An unsupported item."),
        )
    )
    record = RecordNewsSemanticAnnotation(repo)
    classify = ClassifyNewsOnce(repo, record, clock=lambda: _ts(10))

    with pytest.raises(UnsupportedNewsSemanticSourceError):
        await classify()

    # Section 63 step 4/5: classification happens for EVERY candidate
    # before any recording -- the valid item must NOT have been
    # persisted either.
    stored = await repo.list_annotation_vintages_for_item("A1")
    assert stored == ()


@pytest.mark.asyncio
async def test_topic_none_counter() -> None:
    repo = FakeNewsSemanticRepository((_candidate("K1", "FED", "A routine staff announcement."),))
    record = RecordNewsSemanticAnnotation(repo)
    classify = ClassifyNewsOnce(repo, record, clock=lambda: _ts(10))

    result = await classify()

    assert result.topics_none == 1
    assert result.multi_topic_items == 0


@pytest.mark.asyncio
async def test_multi_topic_counter() -> None:
    repo = FakeNewsSemanticRepository(
        (_candidate("K1", "FED", "Monetary policy decision amid rising inflation."),)
    )
    record = RecordNewsSemanticAnnotation(repo)
    classify = ClassifyNewsOnce(repo, record, clock=lambda: _ts(10))

    result = await classify()

    assert result.multi_topic_items == 1
    topics = {topic for topic, _count in result.classifications_by_topic}
    assert NewsTopic.MONETARY_POLICY in topics
    assert NewsTopic.INFLATION_PRICES in topics


@pytest.mark.asyncio
async def test_multi_currency_counter_and_diagnostics() -> None:
    repo = FakeNewsSemanticRepository(
        (_candidate("K1", "FED", "Officials compared notes with the Bank of Canada."),)
    )
    record = RecordNewsSemanticAnnotation(repo)
    classify = ClassifyNewsOnce(repo, record, clock=lambda: _ts(10))

    result = await classify()

    assert result.multi_currency_items == 1
    assert len(result.multi_currency_classifications) == 1
    assert result.multi_currency_classifications[0].news_item_key == "K1"


@pytest.mark.asyncio
async def test_foreign_institution_diagnostics() -> None:
    repo = FakeNewsSemanticRepository(
        (_candidate("K1", "FED", "Officials compared notes with the Bank of Canada."),)
    )
    record = RecordNewsSemanticAnnotation(repo)
    classify = ClassifyNewsOnce(repo, record, clock=lambda: _ts(10))

    result = await classify()

    assert len(result.foreign_institution_classifications) == 1
    diagnostic = result.foreign_institution_classifications[0]
    assert any(e.entity_key == "BANK_OF_CANADA" for e in diagnostic.non_source_entities)


@pytest.mark.asyncio
async def test_algorithm_version_default_is_fx59_v1() -> None:
    repo = FakeNewsSemanticRepository((_candidate("K1", "FED", "Routine update."),))
    record = RecordNewsSemanticAnnotation(repo)
    classify = ClassifyNewsOnce(repo, record, clock=lambda: _ts(10))

    await classify()

    stored = await repo.list_annotation_vintages_for_item("K1")
    assert stored[0].algorithm_version == "fx59_v1"
