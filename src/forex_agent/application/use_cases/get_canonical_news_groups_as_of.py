"""FX-58 Section 45: derives canonical groups as of a requested
instant from `NewsItem`s known by then plus relation state known by
then -- performs no persistence of its own; groups are always
recomputed, never cached as a mutable row (Section 11)."""

from forex_agent.application.ports.news_canonicalization_repository import (
    NewsCanonicalizationRepository,
)
from forex_agent.domain.news_canonical_grouping import NewsCanonicalGroup, derive_canonical_groups
from forex_agent.domain.news_canonical_relation_kind import NewsCanonicalRelationKind
from forex_agent.domain.timestamps import UtcTimestamp


class GetCanonicalNewsGroupsAsOf:
    """FX-58's own group-derivation query -- see the module
    docstring."""

    def __init__(self, repository: NewsCanonicalizationRepository) -> None:
        self._repository = repository

    async def __call__(self, as_of: UtcTimestamp) -> tuple[NewsCanonicalGroup, ...]:
        items = await self._repository.list_items_seen_as_of(as_of)
        relation_states = await self._repository.list_latest_relation_states_as_of(as_of)

        same_story_pairs = tuple(
            (relation.left_news_item_key, relation.right_news_item_key)
            for relation in relation_states
            if relation.relation_kind is NewsCanonicalRelationKind.SAME_STORY
        )
        not_same_story_pairs = tuple(
            (relation.left_news_item_key, relation.right_news_item_key)
            for relation in relation_states
            if relation.relation_kind is NewsCanonicalRelationKind.NOT_SAME_STORY
        )

        return derive_canonical_groups(items, same_story_pairs, not_same_story_pairs)
