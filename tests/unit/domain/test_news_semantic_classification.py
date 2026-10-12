import pytest

from forex_agent.domain.news_currency_relevance import NewsCurrencyRelevance
from forex_agent.domain.news_currency_relevance_reason import NewsCurrencyRelevanceReason
from forex_agent.domain.news_entity_annotation import NewsEntityAnnotation
from forex_agent.domain.news_entity_evidence_kind import NewsEntityEvidenceKind
from forex_agent.domain.news_entity_type import NewsEntityType
from forex_agent.domain.news_semantic_classification import NewsSemanticClassification
from forex_agent.domain.news_topic import NewsTopic
from forex_agent.domain.news_topic_annotation import NewsTopicAnnotation


def _entity(entity_type: NewsEntityType, entity_key: str) -> NewsEntityAnnotation:
    return NewsEntityAnnotation(
        entity_type=entity_type,
        entity_key=entity_key,
        evidence=(NewsEntityEvidenceKind.SOURCE_PROFILE,),
    )


def _currency(code: str) -> NewsCurrencyRelevance:
    return NewsCurrencyRelevance(
        currency_code=code, reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,)
    )


def test_minimal_valid_classification_constructs() -> None:
    classification = NewsSemanticClassification(
        entities=(_entity(NewsEntityType.INSTITUTION, "FEDERAL_RESERVE"),),
        topics=(),
        currency_relevance=(_currency("USD"),),
    )
    assert classification.topics == ()


def test_empty_topic_tuple_allowed() -> None:
    classification = NewsSemanticClassification(
        entities=(_entity(NewsEntityType.INSTITUTION, "FEDERAL_RESERVE"),),
        topics=(),
        currency_relevance=(_currency("USD"),),
    )
    assert classification.topics == ()


def test_empty_entities_rejected() -> None:
    with pytest.raises(ValueError, match="entities"):
        NewsSemanticClassification(entities=(), topics=(), currency_relevance=(_currency("USD"),))


def test_empty_currency_relevance_rejected() -> None:
    with pytest.raises(ValueError, match="currency_relevance"):
        NewsSemanticClassification(
            entities=(_entity(NewsEntityType.INSTITUTION, "FEDERAL_RESERVE"),),
            topics=(),
            currency_relevance=(),
        )


def test_duplicate_entity_identity_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        NewsSemanticClassification(
            entities=(
                _entity(NewsEntityType.INSTITUTION, "FEDERAL_RESERVE"),
                _entity(NewsEntityType.INSTITUTION, "FEDERAL_RESERVE"),
            ),
            topics=(),
            currency_relevance=(_currency("USD"),),
        )


def test_noncanonical_entity_order_rejected() -> None:
    with pytest.raises(ValueError, match="canonical sorted order"):
        NewsSemanticClassification(
            entities=(
                _entity(NewsEntityType.JURISDICTION, "UNITED_STATES"),
                _entity(NewsEntityType.INSTITUTION, "FEDERAL_RESERVE"),
            ),
            topics=(),
            currency_relevance=(_currency("USD"),),
        )


def test_duplicate_topic_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        NewsSemanticClassification(
            entities=(_entity(NewsEntityType.INSTITUTION, "FEDERAL_RESERVE"),),
            topics=(
                NewsTopicAnnotation(topic=NewsTopic.MONETARY_POLICY, matched_terms=("bank rate",)),
                NewsTopicAnnotation(topic=NewsTopic.MONETARY_POLICY, matched_terms=("inflation",)),
            ),
            currency_relevance=(_currency("USD"),),
        )


def test_noncanonical_topic_order_rejected() -> None:
    with pytest.raises(ValueError, match="canonical sorted order"):
        NewsSemanticClassification(
            entities=(_entity(NewsEntityType.INSTITUTION, "FEDERAL_RESERVE"),),
            topics=(
                NewsTopicAnnotation(topic=NewsTopic.MONETARY_POLICY, matched_terms=("bank rate",)),
                NewsTopicAnnotation(topic=NewsTopic.INFLATION_PRICES, matched_terms=("inflation",)),
            ),
            currency_relevance=(_currency("USD"),),
        )


def test_multi_topic_is_valid() -> None:
    classification = NewsSemanticClassification(
        entities=(_entity(NewsEntityType.INSTITUTION, "FEDERAL_RESERVE"),),
        topics=(
            NewsTopicAnnotation(topic=NewsTopic.INFLATION_PRICES, matched_terms=("inflation",)),
            NewsTopicAnnotation(topic=NewsTopic.MONETARY_POLICY, matched_terms=("bank rate",)),
        ),
        currency_relevance=(_currency("USD"),),
    )
    assert len(classification.topics) == 2


def test_duplicate_currency_code_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        NewsSemanticClassification(
            entities=(_entity(NewsEntityType.INSTITUTION, "FEDERAL_RESERVE"),),
            topics=(),
            currency_relevance=(_currency("USD"), _currency("USD")),
        )


def test_noncanonical_currency_order_rejected() -> None:
    with pytest.raises(ValueError, match="canonical sorted order"):
        NewsSemanticClassification(
            entities=(_entity(NewsEntityType.INSTITUTION, "FEDERAL_RESERVE"),),
            topics=(),
            currency_relevance=(_currency("USD"), _currency("CAD")),
        )
