import pytest

from forex_agent.domain.news_topic import NewsTopic
from forex_agent.domain.news_topic_annotation import NewsTopicAnnotation


def test_valid_topic_annotation_constructs() -> None:
    annotation = NewsTopicAnnotation(topic=NewsTopic.MONETARY_POLICY, matched_terms=("bank rate",))
    assert annotation.topic is NewsTopic.MONETARY_POLICY


def test_empty_matched_terms_rejected() -> None:
    with pytest.raises(ValueError, match="matched_terms"):
        NewsTopicAnnotation(topic=NewsTopic.MONETARY_POLICY, matched_terms=())


def test_blank_matched_term_rejected() -> None:
    with pytest.raises(ValueError, match="non-empty string"):
        NewsTopicAnnotation(topic=NewsTopic.MONETARY_POLICY, matched_terms=("bank rate", "  "))


def test_duplicate_matched_terms_rejected() -> None:
    with pytest.raises(ValueError, match="duplicates"):
        NewsTopicAnnotation(
            topic=NewsTopic.MONETARY_POLICY, matched_terms=("bank rate", "bank rate")
        )


def test_noncanonical_matched_terms_order_rejected() -> None:
    with pytest.raises(ValueError, match="canonical sorted order"):
        NewsTopicAnnotation(
            topic=NewsTopic.MONETARY_POLICY,
            matched_terms=("monetary policy", "bank rate"),
        )


def test_wrong_topic_type_rejected() -> None:
    with pytest.raises(TypeError, match="topic"):
        NewsTopicAnnotation(topic="MONETARY_POLICY", matched_terms=("bank rate",))  # type: ignore[arg-type]
