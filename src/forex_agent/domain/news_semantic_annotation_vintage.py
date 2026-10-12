from dataclasses import dataclass

from forex_agent.domain._guards import require_revision_sequence
from forex_agent.domain.news_semantic_classification import NewsSemanticClassification
from forex_agent.domain.timestamps import UtcTimestamp


@dataclass(frozen=True, slots=True)
class NewsSemanticAnnotationVintage:
    """One immutable, point-in-time-safe fact: "as of `availability`,
    FTA's `algorithm_version` classifier produced `classification` for
    `news_item_key`, having classified EXACTLY the `NewsItemVintage`
    at `basis_news_item_revision_sequence`" (FX-59 Section 7/8/10).

    This is a DERIVED evidence layer above `NewsItem`/`NewsItemVintage`
    -- it never mutates, merges, or repoints source identity, and is
    classified at the ITEM level, never against a canonical-group key
    (Section 3): if two source-native items later become `SAME_STORY`
    (FX-58), their own FX-59 histories remain completely untouched.

    `availability` is ALWAYS the instant FTA actually RAN and RECORDED
    this classification (Section 8) -- never `source_published_at`,
    never `NewsItem.first_seen_at`, never the basis `NewsItemVintage`'s
    own `availability`, never an inferred event time. `ClassifyNewsOnce`
    captures this exactly once per run via an injected clock and uses
    that SAME instant for every annotation that run produces (Section
    9).

    `basis_news_item_revision_sequence` pins EXACTLY which
    `NewsItemVintage` was classified (Section 10) -- a future auditor
    can recover the exact headline/summary/body/content-type/channel
    FTA actually classified, via a composite foreign key into
    `news_item_vintages(news_item_key, revision_sequence)`, without
    this table ever copying that content itself.

    A correction (a new basis revision, or a new `algorithm_version`)
    is a NEW vintage with a higher `revision_sequence`, never a rewrite
    of an earlier one -- there is no repository method anywhere that
    `UPDATE`s a stored annotation row (Section 60).

    `algorithm_version` is a stable, non-empty, free-form label (e.g.
    `"fx59_v1"`), never a git commit hash -- a future classification-
    policy change introduces `"fx59_v2"` rather than silently
    reinterpreting what an old classification meant (Section 6)."""

    news_item_key: str
    revision_sequence: int
    availability: UtcTimestamp
    basis_news_item_revision_sequence: int
    algorithm_version: str
    classification: NewsSemanticClassification

    def __post_init__(self) -> None:
        if not isinstance(self.news_item_key, str) or not self.news_item_key.strip():
            raise ValueError(
                f"news_item_key must be a non-empty string, got {self.news_item_key!r}"
            )
        require_revision_sequence(self.revision_sequence)
        if not isinstance(self.availability, UtcTimestamp):
            raise TypeError(
                f"availability must be a UtcTimestamp, got {type(self.availability).__name__}"
            )
        if (
            not isinstance(self.basis_news_item_revision_sequence, int)
            or isinstance(self.basis_news_item_revision_sequence, bool)
            or self.basis_news_item_revision_sequence < 0
        ):
            raise ValueError(
                "basis_news_item_revision_sequence must be a non-negative int, got "
                f"{self.basis_news_item_revision_sequence!r}"
            )
        if not isinstance(self.algorithm_version, str) or not self.algorithm_version.strip():
            raise ValueError(
                f"algorithm_version must be a non-empty string, got {self.algorithm_version!r}"
            )
        if not isinstance(self.classification, NewsSemanticClassification):
            raise TypeError(
                "classification must be a NewsSemanticClassification, got "
                f"{type(self.classification).__name__}"
            )
