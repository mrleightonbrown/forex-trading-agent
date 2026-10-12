"""FX-59: fast, DB-free unit tests for `RecordNewsSemanticAnnotation`
against an in-memory fake repository -- complements the live-Postgres
integration suite in `tests/integration/test_news_semantic_
repository.py`."""

from datetime import UTC, datetime

import pytest

from forex_agent.application.ports.news_semantic_repository import (
    NewsSemanticAnnotationConflictError,
    SemanticAnnotationWriteResult,
)
from forex_agent.application.use_cases.record_news_semantic_annotation import (
    NewsSemanticAnnotationOutcome,
    NewsSemanticDeterminismError,
    OutOfOrderSemanticAnnotationError,
    RecordNewsSemanticAnnotation,
)
from forex_agent.domain.news_currency_relevance import NewsCurrencyRelevance
from forex_agent.domain.news_currency_relevance_reason import NewsCurrencyRelevanceReason
from forex_agent.domain.news_entity_annotation import NewsEntityAnnotation
from forex_agent.domain.news_entity_evidence_kind import NewsEntityEvidenceKind
from forex_agent.domain.news_entity_type import NewsEntityType
from forex_agent.domain.news_semantic_annotation_vintage import NewsSemanticAnnotationVintage
from forex_agent.domain.news_semantic_classification import NewsSemanticClassification
from forex_agent.domain.news_semantic_classifying import NewsSemanticClassificationCandidate
from forex_agent.domain.timestamps import UtcTimestamp


class FakeNewsSemanticRepository:
    """In-memory implementation of the FULL `NewsSemanticRepository`
    Protocol -- `RecordNewsSemanticAnnotation` itself only ever calls
    `latest_annotation_for_item`/`add_annotation_vintage`, but every
    method is implemented so this fake structurally proves the full
    Protocol contract (mirrors `FakeNewsCanonicalizationRepository`)."""

    def __init__(self, *, simulate_lost_race: bool = False) -> None:
        self._annotations: dict[str, list[NewsSemanticAnnotationVintage]] = {}
        self._simulate_lost_race = simulate_lost_race

    async def list_candidates_as_of(
        self, as_of: UtcTimestamp, *, include_backfill: bool = False
    ) -> tuple[NewsSemanticClassificationCandidate, ...]:
        raise NotImplementedError("not used by RecordNewsSemanticAnnotation")

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
        rows = [
            r
            for r in self._annotations.get(news_item_key, [])
            if r.availability.value <= as_of.value
        ]
        if not rows:
            return None
        return max(rows, key=lambda r: (r.availability.value, r.revision_sequence))

    async def list_annotation_vintages_for_item(
        self, news_item_key: str
    ) -> tuple[NewsSemanticAnnotationVintage, ...]:
        return tuple(self._annotations.get(news_item_key, []))

    async def list_latest_annotation_states_as_of(
        self, as_of: UtcTimestamp
    ) -> tuple[NewsSemanticAnnotationVintage, ...]:
        raise NotImplementedError("not used by RecordNewsSemanticAnnotation")

    async def add_annotation_vintage(
        self, vintage: NewsSemanticAnnotationVintage
    ) -> SemanticAnnotationWriteResult:
        rows = self._annotations.setdefault(vintage.news_item_key, [])
        for existing in rows:
            if existing.revision_sequence == vintage.revision_sequence:
                if existing == vintage:
                    return SemanticAnnotationWriteResult(inserted=False)
                raise NewsSemanticAnnotationConflictError(existing, vintage)
        rows.append(vintage)
        if self._simulate_lost_race:
            return SemanticAnnotationWriteResult(inserted=False)
        return SemanticAnnotationWriteResult(inserted=True)


def _ts(hour: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, hour, tzinfo=UTC))


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


@pytest.mark.asyncio
async def test_first_classification_creates_revision_zero() -> None:
    repo = FakeNewsSemanticRepository()
    record = RecordNewsSemanticAnnotation(repo)

    result = await record(
        "K1",
        0,
        availability=_ts(10),
        classification=_classification(),
        algorithm_version="fx59_v1",
    )

    assert result.outcome is NewsSemanticAnnotationOutcome.CREATED
    assert result.annotation.revision_sequence == 0


@pytest.mark.asyncio
async def test_identical_rerun_is_unchanged() -> None:
    repo = FakeNewsSemanticRepository()
    record = RecordNewsSemanticAnnotation(repo)

    await record(
        "K1", 0, availability=_ts(10), classification=_classification(), algorithm_version="fx59_v1"
    )
    second = await record(
        "K1", 0, availability=_ts(11), classification=_classification(), algorithm_version="fx59_v1"
    )

    assert second.outcome is NewsSemanticAnnotationOutcome.UNCHANGED
    assert second.annotation.revision_sequence == 0
    assert second.annotation.availability == _ts(10)


@pytest.mark.asyncio
async def test_basis_revision_changed_mints_new_revision_even_if_output_identical() -> None:
    repo = FakeNewsSemanticRepository()
    record = RecordNewsSemanticAnnotation(repo)

    await record(
        "K1", 0, availability=_ts(10), classification=_classification(), algorithm_version="fx59_v1"
    )
    second = await record(
        "K1", 1, availability=_ts(11), classification=_classification(), algorithm_version="fx59_v1"
    )

    assert second.outcome is NewsSemanticAnnotationOutcome.REVISION_ADDED
    assert second.annotation.revision_sequence == 1
    assert second.annotation.basis_news_item_revision_sequence == 1


@pytest.mark.asyncio
async def test_algorithm_version_changed_mints_new_revision_even_if_output_identical() -> None:
    repo = FakeNewsSemanticRepository()
    record = RecordNewsSemanticAnnotation(repo)

    await record(
        "K1", 0, availability=_ts(10), classification=_classification(), algorithm_version="fx59_v1"
    )
    second = await record(
        "K1", 0, availability=_ts(11), classification=_classification(), algorithm_version="fx59_v2"
    )

    assert second.outcome is NewsSemanticAnnotationOutcome.REVISION_ADDED
    assert second.annotation.algorithm_version == "fx59_v2"


@pytest.mark.asyncio
async def test_same_basis_same_algorithm_different_output_is_determinism_error() -> None:
    repo = FakeNewsSemanticRepository()
    record = RecordNewsSemanticAnnotation(repo)

    await record(
        "K1",
        0,
        availability=_ts(10),
        classification=_classification("USD"),
        algorithm_version="fx59_v1",
    )

    with pytest.raises(NewsSemanticDeterminismError):
        await record(
            "K1",
            0,
            availability=_ts(11),
            classification=_classification("CAD"),
            algorithm_version="fx59_v1",
        )


@pytest.mark.asyncio
async def test_out_of_order_availability_raises() -> None:
    repo = FakeNewsSemanticRepository()
    record = RecordNewsSemanticAnnotation(repo)

    await record(
        "K1", 0, availability=_ts(10), classification=_classification(), algorithm_version="fx59_v1"
    )

    with pytest.raises(OutOfOrderSemanticAnnotationError):
        await record(
            "K1",
            1,
            availability=_ts(9),
            classification=_classification(),
            algorithm_version="fx59_v1",
        )


@pytest.mark.asyncio
async def test_equal_availability_allowed() -> None:
    repo = FakeNewsSemanticRepository()
    record = RecordNewsSemanticAnnotation(repo)

    await record(
        "K1", 0, availability=_ts(10), classification=_classification(), algorithm_version="fx59_v1"
    )
    result = await record(
        "K1", 1, availability=_ts(10), classification=_classification(), algorithm_version="fx59_v1"
    )

    assert result.outcome is NewsSemanticAnnotationOutcome.REVISION_ADDED


@pytest.mark.asyncio
async def test_repository_inserted_false_reports_unchanged_not_created() -> None:
    repo = FakeNewsSemanticRepository(simulate_lost_race=True)
    record = RecordNewsSemanticAnnotation(repo)

    result = await record(
        "K1", 0, availability=_ts(10), classification=_classification(), algorithm_version="fx59_v1"
    )

    assert result.outcome is NewsSemanticAnnotationOutcome.UNCHANGED
    stored = await repo.list_annotation_vintages_for_item("K1")
    assert len(stored) == 1


@pytest.mark.asyncio
async def test_repository_inserted_false_on_revision_reports_unchanged_not_revision_added() -> None:
    repo = FakeNewsSemanticRepository()
    record = RecordNewsSemanticAnnotation(repo)
    await record(
        "K1", 0, availability=_ts(10), classification=_classification(), algorithm_version="fx59_v1"
    )
    repo._simulate_lost_race = True

    result = await record(
        "K1", 1, availability=_ts(11), classification=_classification(), algorithm_version="fx59_v1"
    )

    assert result.outcome is NewsSemanticAnnotationOutcome.UNCHANGED
    stored = await repo.list_annotation_vintages_for_item("K1")
    assert len(stored) == 2


# --- FX-59H: determinism enforced across the ENTIRE historical record ----


@pytest.mark.asyncio
async def test_repeated_old_algorithm_with_same_output_is_revision_added() -> None:
    # T1: v1 -> A. T2: v2 -> B. T3: v1 -> A again.
    repo = FakeNewsSemanticRepository()
    record = RecordNewsSemanticAnnotation(repo)

    await record(
        "K1",
        0,
        availability=_ts(10),
        classification=_classification("USD"),
        algorithm_version="fx59_v1",
    )
    await record(
        "K1",
        0,
        availability=_ts(11),
        classification=_classification("CAD"),
        algorithm_version="fx59_v2",
    )
    result = await record(
        "K1",
        0,
        availability=_ts(12),
        classification=_classification("USD"),
        algorithm_version="fx59_v1",
    )

    # Must be REVISION_ADDED, not UNCHANGED -- the item's own latest
    # row at T3 is the fx59_v2 row, so fx59_v1 becoming current again
    # is a genuine new fact FTA is recording.
    assert result.outcome is NewsSemanticAnnotationOutcome.REVISION_ADDED
    assert result.annotation.revision_sequence == 2
    assert result.annotation.algorithm_version == "fx59_v1"
    stored = await repo.list_annotation_vintages_for_item("K1")
    assert len(stored) == 3


@pytest.mark.asyncio
async def test_repeated_old_algorithm_with_different_output_is_determinism_error() -> None:
    # T1: v1 -> A. T2: v2 -> B. T3: v1 -> C (C != A).
    repo = FakeNewsSemanticRepository()
    record = RecordNewsSemanticAnnotation(repo)

    await record(
        "K1",
        0,
        availability=_ts(10),
        classification=_classification("USD"),
        algorithm_version="fx59_v1",
    )
    await record(
        "K1",
        0,
        availability=_ts(11),
        classification=_classification("CAD"),
        algorithm_version="fx59_v2",
    )

    with pytest.raises(NewsSemanticDeterminismError):
        await record(
            "K1",
            0,
            availability=_ts(12),
            classification=_classification("EUR"),  # a THIRD, different output for fx59_v1
            algorithm_version="fx59_v1",
        )

    # No third row minted -- the two existing rows are untouched.
    stored = await repo.list_annotation_vintages_for_item("K1")
    assert len(stored) == 2
    assert {s.revision_sequence for s in stored} == {0, 1}


@pytest.mark.asyncio
async def test_different_basis_same_algorithm_different_output_is_a_valid_revision() -> None:
    # basis0 + v1 -> A, then basis1 + v1 -> B -- the basis dimension
    # is part of the deterministic key, so this is NOT a conflict.
    repo = FakeNewsSemanticRepository()
    record = RecordNewsSemanticAnnotation(repo)

    await record(
        "K1",
        0,
        availability=_ts(10),
        classification=_classification("USD"),
        algorithm_version="fx59_v1",
    )
    result = await record(
        "K1",
        1,
        availability=_ts(11),
        classification=_classification("CAD"),
        algorithm_version="fx59_v1",
    )

    assert result.outcome is NewsSemanticAnnotationOutcome.REVISION_ADDED
    assert result.annotation.basis_news_item_revision_sequence == 1


@pytest.mark.asyncio
async def test_out_of_order_availability_wins_over_historical_determinism_check() -> None:
    # Construct a scenario where the incoming call would ALSO violate
    # the historical determinism invariant (same basis+algorithm as an
    # existing row, different output) -- the ordering check must still
    # fire FIRST, never the determinism check.
    repo = FakeNewsSemanticRepository()
    record = RecordNewsSemanticAnnotation(repo)

    await record(
        "K1",
        0,
        availability=_ts(10),
        classification=_classification("USD"),
        algorithm_version="fx59_v1",
    )
    await record(
        "K1",
        0,
        availability=_ts(12),
        classification=_classification("CAD"),
        algorithm_version="fx59_v2",
    )

    with pytest.raises(OutOfOrderSemanticAnnotationError):
        await record(
            "K1",
            0,
            availability=_ts(11),  # earlier than the latest (12), but later than rev0 (10)
            classification=_classification("EUR"),  # would ALSO conflict with the fx59_v1/USD row
            algorithm_version="fx59_v1",
        )

    stored = await repo.list_annotation_vintages_for_item("K1")
    assert len(stored) == 2
