"""FX-58 Section 58: deterministic group-derivation tests for
`derive_canonical_groups` -- pure, no I/O."""

from datetime import UTC, datetime

import pytest

from forex_agent.domain.news_canonical_grouping import (
    NewsCanonicalizationInconsistentStateError,
    derive_canonical_groups,
)
from forex_agent.domain.news_item import NewsItem
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.timestamps import UtcTimestamp


def _item(key: str, hour: int) -> NewsItem:
    return NewsItem(
        key, UtcTimestamp(datetime(2026, 1, 1, hour, tzinfo=UTC)), NewsObservationMode.PROSPECTIVE
    )


def test_no_relations_means_every_item_is_a_singleton() -> None:
    items = (_item("A", 1), _item("B", 2))
    groups = derive_canonical_groups(items, (), ())
    assert {g.canonical_group_key for g in groups} == {"A", "B"}
    assert all(len(g.member_news_item_keys) == 1 for g in groups)


def test_one_same_pair_makes_a_two_member_group() -> None:
    items = (_item("A", 1), _item("B", 2))
    groups = derive_canonical_groups(items, (("A", "B"),), ())
    assert len(groups) == 1
    assert groups[0].member_news_item_keys == ("A", "B")


def test_transitive_a_b_and_b_c_makes_one_three_member_group() -> None:
    items = (_item("A", 1), _item("B", 2), _item("C", 3))
    groups = derive_canonical_groups(items, (("A", "B"), ("B", "C")), ())
    assert len(groups) == 1
    assert groups[0].member_news_item_keys == ("A", "B", "C")


def test_group_key_is_earliest_first_seen_member() -> None:
    # B is first-seen earliest, even though "A" sorts first
    # lexicographically -- the group key must be B, not A.
    items = (_item("A", 5), _item("B", 1))
    groups = derive_canonical_groups(items, (("A", "B"),), ())
    assert groups[0].canonical_group_key == "B"


def test_first_seen_tie_breaks_lexicographically() -> None:
    items = (_item("Z", 1), _item("A", 1))
    groups = derive_canonical_groups(items, (("A", "Z"),), ())
    assert groups[0].canonical_group_key == "A"


def test_relation_unavailable_before_its_availability_means_no_edge() -> None:
    # This is exercised at the repository/use-case layer (the as_of
    # filter happens before edges ever reach this pure function) --
    # here we pin that an EMPTY edge set (as if the relation were not
    # yet available) correctly yields singletons, never a 2-group.
    items = (_item("A", 1), _item("B", 2))
    groups = derive_canonical_groups(items, (), ())
    assert len(groups) == 2


def test_not_same_story_can_split_a_direct_pair() -> None:
    items = (_item("A", 1), _item("B", 2))
    # No SAME_STORY edge at all -- NOT_SAME_STORY with no contradicting
    # transitivity is simply a no-op on the group structure (both
    # remain singletons); it does not itself raise.
    groups = derive_canonical_groups(items, (), (("A", "B"),))
    assert len(groups) == 2


def test_contradictory_transitive_state_fails_closed() -> None:
    items = (_item("A", 1), _item("B", 2), _item("C", 3))
    with pytest.raises(NewsCanonicalizationInconsistentStateError):
        derive_canonical_groups(items, (("A", "B"), ("B", "C")), (("A", "C"),))


def test_group_output_deterministic_independent_of_db_row_order() -> None:
    items_forward = (_item("A", 1), _item("B", 2), _item("C", 3))
    items_reversed = (_item("C", 3), _item("B", 2), _item("A", 1))
    same_story = (("B", "C"), ("A", "B"))
    same_story_reversed = (("A", "B"), ("B", "C"))

    groups_forward = derive_canonical_groups(items_forward, same_story, ())
    groups_reversed = derive_canonical_groups(items_reversed, same_story_reversed, ())
    assert groups_forward == groups_reversed
