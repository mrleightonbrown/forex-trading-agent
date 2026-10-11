"""FX-58 Sections 11-14: canonical groups are DERIVED connected
components over `SAME_STORY` relation edges, as of a requested
instant -- never a persisted, mutable "canonical group" row. This
avoids group-row orphan races, mutable master IDs, destructive merge
semantics, and group-merge lineage tables entirely; only the
evidence-level pair relationships are ever stored.
"""

from dataclasses import dataclass

from forex_agent.domain.news_item import NewsItem


@dataclass(frozen=True, slots=True)
class NewsCanonicalGroup:
    """One derived connected component (FX-58 Section 45).
    `canonical_group_key` is a DETERMINISTIC derived identifier
    (the member with the earliest `NewsItem.first_seen_at`, tied-
    broken lexicographically by `news_item_key`, Section 13) -- NEVER
    a persisted mutable identity, and NEVER an implication of source
    trustworthiness/quality/primacy (Section 46: that is FX-EPIC-09's
    own future job, not this one's)."""

    canonical_group_key: str
    member_news_item_keys: tuple[str, ...]


class NewsCanonicalizationInconsistentStateError(Exception):
    """Raised when the latest stored relation state is self-
    contradictory: a `NOT_SAME_STORY` pair that `SAME_STORY`
    transitivity would otherwise place in the same connected
    component (FX-58 Section 14/40) -- e.g. A-SAME-B, B-SAME-C, but
    A-NOT_SAME-C. Never silently resolved in either direction (never
    merged into `{A,B,C}`, never silently ignoring the correction) --
    this is contradictory stored state requiring human review."""

    def __init__(self, left_news_item_key: str, right_news_item_key: str) -> None:
        self.left_news_item_key = left_news_item_key
        self.right_news_item_key = right_news_item_key
        super().__init__(
            f"contradictory canonical relation state: ({left_news_item_key!r}, "
            f"{right_news_item_key!r}) has a latest NOT_SAME_STORY relation, but SAME_STORY "
            "transitivity through other relations would place them in the same connected "
            "component -- refusing to silently merge or silently ignore the correction"
        )


def derive_canonical_groups(
    items: tuple[NewsItem, ...],
    same_story_pairs: tuple[tuple[str, str], ...],
    not_same_story_pairs: tuple[tuple[str, str], ...],
) -> tuple[NewsCanonicalGroup, ...]:
    """Builds connected components over `same_story_pairs` across
    every known `items`, then fails closed (`NewsCanonicalization
    InconsistentStateError`) if any `not_same_story_pairs` edge would
    otherwise land inside one component via transitivity (Section 14).
    An item with no `SAME_STORY` edge is its own singleton component
    (Section 13/44) -- deterministic, independent of input order."""
    parent: dict[str, str] = {item.news_item_key: item.news_item_key for item in items}
    first_seen_by_key = {item.news_item_key: item.first_seen_at for item in items}

    def find(key: str) -> str:
        root = key
        while parent[root] != root:
            root = parent[root]
        while parent[key] != root:
            parent[key], key = root, parent[key]
        return root

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[left_root] = right_root

    for left, right in same_story_pairs:
        union(left, right)

    for left, right in not_same_story_pairs:
        if find(left) == find(right):
            raise NewsCanonicalizationInconsistentStateError(left, right)

    components: dict[str, list[str]] = {}
    for key in parent:
        components.setdefault(find(key), []).append(key)

    groups = tuple(
        NewsCanonicalGroup(
            canonical_group_key=min(members, key=lambda k: (first_seen_by_key[k].value, k)),
            member_news_item_keys=tuple(sorted(members)),
        )
        for members in components.values()
    )
    return tuple(sorted(groups, key=lambda g: g.canonical_group_key))
