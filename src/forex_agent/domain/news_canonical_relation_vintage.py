from dataclasses import dataclass

from forex_agent.domain._guards import require_revision_sequence
from forex_agent.domain.news_canonical_relation_kind import NewsCanonicalRelationKind
from forex_agent.domain.news_canonicalization_method import NewsCanonicalizationMethod
from forex_agent.domain.timestamps import UtcTimestamp

_AUTOMATIC_METHODS = (
    NewsCanonicalizationMethod.EXACT_CANONICAL_URL,
    NewsCanonicalizationMethod.EXACT_BODY_TEXT,
)


@dataclass(frozen=True, slots=True)
class NewsCanonicalRelationVintage:
    """One immutable, point-in-time-safe fact: "as of `availability`,
    FTA decided `relation_kind` for the pair `(left_news_item_key,
    right_news_item_key)`" (FX-58 Section 4/7).

    This is a DERIVED evidence layer above `NewsItem`/`NewsItemVintage`
    -- it never mutates, merges, or repoints source identity. A
    correction is a NEW vintage with a higher `revision_sequence`,
    never a rewrite of an earlier one (Section 15): no repository
    method anywhere issues an `UPDATE` against a stored relation row.

    `availability` is ALWAYS the instant FTA actually made/recorded
    THIS canonicalization decision (Section 7) -- never either
    source's own publication timestamp, either `NewsItem.first_seen_
    at`, either item's own vintage `availability`, or any inferred
    event time. `CanonicalizeNewsOnce` captures this exactly once per
    run via an injected clock and uses that SAME instant for every
    relation decision that run produces (Section 8).

    `left_item_revision_sequence`/`right_item_revision_sequence` pin
    EXACTLY which `NewsItemVintage` of each item was compared to reach
    this decision (Section 9) -- a future auditor can reconstruct the
    exact headline/summary/body/URL FTA compared, via a composite
    foreign key into `news_item_vintages(news_item_key, revision_
    sequence)`, without this table ever copying that content itself.

    `algorithm_version` is a stable, non-empty, free-form label (e.g.
    `"fx58_v1"`) identifying which matching-policy version produced
    this decision (Section 10) -- never a git commit hash: a future
    policy change introduces `"fx58_v2"` rather than silently
    reinterpreting what an old decision meant.

    Canonical pair orientation: `left_news_item_key <
    right_news_item_key`, lexicographically, always -- a self-
    relation is forbidden (Section 4). This ordering is purely a
    deterministic storage convention; it carries no meaning about
    which item is "primary."

    Fields:
        left_news_item_key: the lexicographically SMALLER of the two
            related `NewsItem.news_item_key` values.
        right_news_item_key: the lexicographically LARGER of the two.
        revision_sequence: 0 for this PAIR's first recorded decision,
            incrementing for each subsequent one (Section 31).
        availability: FTA's own decision time for this exact
            revision (see above).
        relation_kind: see `NewsCanonicalRelationKind`.
        method: see `NewsCanonicalizationMethod`. An automatic method
            (anything other than `MANUAL_REVIEW`) may ONLY ever pair
            with `SAME_STORY`; `NOT_SAME_STORY` may ONLY ever pair
            with `MANUAL_REVIEW` (both enforced below, Section 56).
        left_item_revision_sequence: the `NewsItemVintage.revision_
            sequence` of `left_news_item_key` actually compared to
            reach this decision.
        right_item_revision_sequence: the `NewsItemVintage.revision_
            sequence` of `right_news_item_key` actually compared to
            reach this decision.
        algorithm_version: see above.
    """

    left_news_item_key: str
    right_news_item_key: str
    revision_sequence: int
    availability: UtcTimestamp
    relation_kind: NewsCanonicalRelationKind
    method: NewsCanonicalizationMethod
    left_item_revision_sequence: int
    right_item_revision_sequence: int
    algorithm_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.left_news_item_key, str) or not self.left_news_item_key.strip():
            raise ValueError(
                f"left_news_item_key must be a non-empty string, got {self.left_news_item_key!r}"
            )
        if not isinstance(self.right_news_item_key, str) or not self.right_news_item_key.strip():
            raise ValueError(
                f"right_news_item_key must be a non-empty string, got {self.right_news_item_key!r}"
            )
        if self.left_news_item_key == self.right_news_item_key:
            raise ValueError(
                f"self-relation forbidden: left_news_item_key == right_news_item_key == "
                f"{self.left_news_item_key!r}"
            )
        if self.left_news_item_key >= self.right_news_item_key:
            raise ValueError(
                "left_news_item_key must be lexicographically less than right_news_item_key -- "
                f"got left={self.left_news_item_key!r}, right={self.right_news_item_key!r}"
            )
        require_revision_sequence(self.revision_sequence)
        if not isinstance(self.availability, UtcTimestamp):
            raise TypeError(
                f"availability must be a UtcTimestamp, got {type(self.availability).__name__}"
            )
        if not isinstance(self.relation_kind, NewsCanonicalRelationKind):
            raise TypeError(
                "relation_kind must be a NewsCanonicalRelationKind, got "
                f"{type(self.relation_kind).__name__}"
            )
        if not isinstance(self.method, NewsCanonicalizationMethod):
            raise TypeError(
                f"method must be a NewsCanonicalizationMethod, got {type(self.method).__name__}"
            )
        _require_nonnegative_int("left_item_revision_sequence", self.left_item_revision_sequence)
        _require_nonnegative_int("right_item_revision_sequence", self.right_item_revision_sequence)
        if not isinstance(self.algorithm_version, str) or not self.algorithm_version.strip():
            raise ValueError(
                f"algorithm_version must be a non-empty string, got {self.algorithm_version!r}"
            )
        if (
            self.method in _AUTOMATIC_METHODS
            and self.relation_kind is not NewsCanonicalRelationKind.SAME_STORY
        ):
            raise ValueError(
                f"method={self.method!r} is an automatic method and may only ever pair "
                f"with SAME_STORY, got relation_kind={self.relation_kind!r}"
            )
        if (
            self.relation_kind is NewsCanonicalRelationKind.NOT_SAME_STORY
            and self.method is not NewsCanonicalizationMethod.MANUAL_REVIEW
        ):
            raise ValueError(
                f"relation_kind=NOT_SAME_STORY may only ever pair with method=MANUAL_REVIEW, "
                f"got method={self.method!r}"
            )


def _require_nonnegative_int(name: str, value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{name} must not be negative, got {value}")
