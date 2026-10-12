from dataclasses import dataclass

from forex_agent.domain.news_topic import NewsTopic


@dataclass(frozen=True, slots=True)
class NewsTopicAnnotation:
    """One topic FTA's `fx59_v1` classifier found for one `NewsItem`,
    with the exact matched phrase(s) that caused it to fire (FX-59
    Section 34) -- never a full article excerpt, and never a score.

    `matched_terms` is a non-empty, canonically sorted, deduplicated
    tuple of the curated rule phrases that matched (e.g.
    `("federal funds rate", "monetary policy")`) -- enough for a human
    reviewer to understand WHY this topic fired, without storing raw
    text."""

    topic: NewsTopic
    matched_terms: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.topic, NewsTopic):
            raise TypeError(f"topic must be a NewsTopic, got {type(self.topic).__name__}")
        if not isinstance(self.matched_terms, tuple) or not self.matched_terms:
            raise ValueError(f"matched_terms must be a non-empty tuple, got {self.matched_terms!r}")
        for term in self.matched_terms:
            if not isinstance(term, str) or not term.strip():
                raise ValueError(
                    f"each matched_terms entry must be a non-empty string, got {term!r}"
                )
        if len(set(self.matched_terms)) != len(self.matched_terms):
            raise ValueError(
                f"matched_terms must not contain duplicates, got {self.matched_terms!r}"
            )
        canonical_terms = tuple(sorted(self.matched_terms))
        if self.matched_terms != canonical_terms:
            raise ValueError(
                f"matched_terms must be in canonical sorted order, got {self.matched_terms!r}, "
                f"expected {canonical_terms!r}"
            )
