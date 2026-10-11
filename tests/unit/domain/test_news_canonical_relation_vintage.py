"""FX-58 Section 56: `NewsCanonicalRelationVintage` domain validation
tests."""

from datetime import UTC, datetime

import pytest

from forex_agent.domain.news_canonical_relation_kind import NewsCanonicalRelationKind
from forex_agent.domain.news_canonical_relation_vintage import NewsCanonicalRelationVintage
from forex_agent.domain.news_canonicalization_method import NewsCanonicalizationMethod
from forex_agent.domain.timestamps import UtcTimestamp

_TS = UtcTimestamp(datetime(2026, 1, 1, tzinfo=UTC))


def _relation(**overrides: object) -> NewsCanonicalRelationVintage:
    defaults: dict[str, object] = {
        "left_news_item_key": "A",
        "right_news_item_key": "B",
        "revision_sequence": 0,
        "availability": _TS,
        "relation_kind": NewsCanonicalRelationKind.SAME_STORY,
        "method": NewsCanonicalizationMethod.EXACT_CANONICAL_URL,
        "left_item_revision_sequence": 0,
        "right_item_revision_sequence": 0,
        "algorithm_version": "fx58_v1",
    }
    defaults.update(overrides)
    return NewsCanonicalRelationVintage(**defaults)  # type: ignore[arg-type]


def test_valid_relation_constructs() -> None:
    relation = _relation()
    assert relation.left_news_item_key == "A"
    assert relation.right_news_item_key == "B"


def test_canonical_left_right_ordering_enforced() -> None:
    with pytest.raises(ValueError):
        _relation(left_news_item_key="B", right_news_item_key="A")


def test_self_pair_rejected() -> None:
    with pytest.raises(ValueError):
        _relation(left_news_item_key="A", right_news_item_key="A")


def test_blank_left_key_rejected() -> None:
    with pytest.raises(ValueError):
        _relation(left_news_item_key="   ")


def test_blank_right_key_rejected() -> None:
    with pytest.raises(ValueError):
        _relation(right_news_item_key="")


def test_negative_revision_sequence_rejected() -> None:
    with pytest.raises(ValueError):
        _relation(revision_sequence=-1)


def test_negative_left_item_revision_sequence_rejected() -> None:
    with pytest.raises(ValueError):
        _relation(left_item_revision_sequence=-1)


def test_negative_right_item_revision_sequence_rejected() -> None:
    with pytest.raises(ValueError):
        _relation(right_item_revision_sequence=-1)


def test_blank_algorithm_version_rejected() -> None:
    with pytest.raises(ValueError):
        _relation(algorithm_version="")
    with pytest.raises(ValueError):
        _relation(algorithm_version="   ")


def test_automatic_methods_only_valid_with_same_story() -> None:
    # FX-58H Section 5: EXACT_HEADLINE_AND_SUMMARY no longer exists
    # as a NewsCanonicalizationMethod member at all -- only the two
    # remaining automatic methods are exercised here.
    for method in (
        NewsCanonicalizationMethod.EXACT_CANONICAL_URL,
        NewsCanonicalizationMethod.EXACT_BODY_TEXT,
    ):
        _relation(method=method, relation_kind=NewsCanonicalRelationKind.SAME_STORY)
        with pytest.raises(ValueError):
            _relation(method=method, relation_kind=NewsCanonicalRelationKind.NOT_SAME_STORY)


def test_exact_headline_and_summary_no_longer_exists_as_a_method() -> None:
    # FX-58H Section 5: removed entirely, never merely deprecated.
    assert not hasattr(NewsCanonicalizationMethod, "EXACT_HEADLINE_AND_SUMMARY")


def test_not_same_story_requires_manual_review() -> None:
    _relation(
        method=NewsCanonicalizationMethod.MANUAL_REVIEW,
        relation_kind=NewsCanonicalRelationKind.NOT_SAME_STORY,
    )
    with pytest.raises(ValueError):
        _relation(
            method=NewsCanonicalizationMethod.EXACT_CANONICAL_URL,
            relation_kind=NewsCanonicalRelationKind.NOT_SAME_STORY,
        )


def test_manual_review_may_also_pair_with_same_story() -> None:
    # A future human reviewer may manually CONFIRM a same-story
    # relation an automatic rule never caught -- the schema permits
    # this even though FX-58 v1's own automatic matcher never
    # produces it (Section 6).
    relation = _relation(
        method=NewsCanonicalizationMethod.MANUAL_REVIEW,
        relation_kind=NewsCanonicalRelationKind.SAME_STORY,
    )
    assert relation.relation_kind is NewsCanonicalRelationKind.SAME_STORY
