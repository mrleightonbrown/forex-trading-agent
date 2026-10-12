from datetime import UTC, datetime

import pytest

from forex_agent.domain.news_currency_relevance import NewsCurrencyRelevance
from forex_agent.domain.news_currency_relevance_reason import NewsCurrencyRelevanceReason
from forex_agent.domain.news_entity_annotation import NewsEntityAnnotation
from forex_agent.domain.news_entity_evidence_kind import NewsEntityEvidenceKind
from forex_agent.domain.news_entity_type import NewsEntityType
from forex_agent.domain.news_semantic_annotation_vintage import NewsSemanticAnnotationVintage
from forex_agent.domain.news_semantic_classification import NewsSemanticClassification
from forex_agent.domain.timestamps import UtcTimestamp


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


def _ts(hour: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, hour, tzinfo=UTC))


def test_valid_annotation_vintage_constructs() -> None:
    vintage = NewsSemanticAnnotationVintage(
        news_item_key="K1",
        revision_sequence=0,
        availability=_ts(10),
        basis_news_item_revision_sequence=0,
        algorithm_version="fx59_v1",
        classification=_classification(),
    )
    assert vintage.revision_sequence == 0


def test_negative_revision_sequence_rejected() -> None:
    with pytest.raises((ValueError, TypeError)):
        NewsSemanticAnnotationVintage(
            news_item_key="K1",
            revision_sequence=-1,
            availability=_ts(10),
            basis_news_item_revision_sequence=0,
            algorithm_version="fx59_v1",
            classification=_classification(),
        )


def test_negative_basis_revision_sequence_rejected() -> None:
    with pytest.raises(ValueError, match="basis_news_item_revision_sequence"):
        NewsSemanticAnnotationVintage(
            news_item_key="K1",
            revision_sequence=0,
            availability=_ts(10),
            basis_news_item_revision_sequence=-1,
            algorithm_version="fx59_v1",
            classification=_classification(),
        )


def test_blank_algorithm_version_rejected() -> None:
    with pytest.raises(ValueError, match="algorithm_version"):
        NewsSemanticAnnotationVintage(
            news_item_key="K1",
            revision_sequence=0,
            availability=_ts(10),
            basis_news_item_revision_sequence=0,
            algorithm_version="   ",
            classification=_classification(),
        )


def test_blank_news_item_key_rejected() -> None:
    with pytest.raises(ValueError, match="news_item_key"):
        NewsSemanticAnnotationVintage(
            news_item_key="  ",
            revision_sequence=0,
            availability=_ts(10),
            basis_news_item_revision_sequence=0,
            algorithm_version="fx59_v1",
            classification=_classification(),
        )


def test_wrong_availability_type_rejected() -> None:
    with pytest.raises(TypeError, match="availability"):
        NewsSemanticAnnotationVintage(
            news_item_key="K1",
            revision_sequence=0,
            availability=datetime(2026, 1, 1, 10, tzinfo=UTC),  # type: ignore[arg-type]
            basis_news_item_revision_sequence=0,
            algorithm_version="fx59_v1",
            classification=_classification(),
        )


def test_wrong_classification_type_rejected() -> None:
    with pytest.raises(TypeError, match="classification"):
        NewsSemanticAnnotationVintage(
            news_item_key="K1",
            revision_sequence=0,
            availability=_ts(10),
            basis_news_item_revision_sequence=0,
            algorithm_version="fx59_v1",
            classification="not a classification",  # type: ignore[arg-type]
        )
