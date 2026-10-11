"""FX-58: the conservative, deterministic, exact-match-only matching
policy (`fx58_v1`) -- Sections 16-24. Every rule here compares
NORMALIZED (never fuzzy) text/URLs and requires EXACT equality plus a
minimum length where specified; there is no scoring, no confidence
percentage, no time-window heuristic, and no headline-only or
summary-only rule. False equivalence (a merge of two genuinely
distinct stories) is considered far worse than a missed duplicate, so
every rule here is deliberately high-precision, low-recall.
"""

from dataclasses import dataclass

from forex_agent.domain.news_canonicalization_method import NewsCanonicalizationMethod
from forex_agent.domain.news_text_normalization import normalize_canonical_url, normalize_text
from forex_agent.domain.timestamps import UtcTimestamp

_MIN_BODY_LENGTH = 200
_MIN_SUMMARY_LENGTH = 80


@dataclass(frozen=True, slots=True)
class CanonicalizationCandidate:
    """The current evidence FTA would compare for one `NewsItem`
    when canonicalizing (FX-58 Section 30) -- built from that item's
    own identity plus the ONE `NewsItemVintage` actually used for
    matching (its latest evidence-eligible vintage as of the run,
    Section 27). Carries no parsing logic of its own; a repository
    projects this directly from already-persisted, already-validated
    `NewsItem`/`NewsItemVintage` objects."""

    news_item_key: str
    first_seen_at: UtcTimestamp
    revision_sequence: int
    availability: UtcTimestamp
    headline: str
    summary: str | None
    body_text: str | None
    canonical_url: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.news_item_key, str) or not self.news_item_key.strip():
            raise ValueError(
                f"news_item_key must be a non-empty string, got {self.news_item_key!r}"
            )
        if not isinstance(self.first_seen_at, UtcTimestamp):
            raise TypeError(
                f"first_seen_at must be a UtcTimestamp, got {type(self.first_seen_at).__name__}"
            )
        if self.revision_sequence < 0:
            raise ValueError(
                f"revision_sequence must not be negative, got {self.revision_sequence}"
            )
        if not isinstance(self.availability, UtcTimestamp):
            raise TypeError(
                f"availability must be a UtcTimestamp, got {type(self.availability).__name__}"
            )
        if not isinstance(self.headline, str) or not self.headline.strip():
            raise ValueError(f"headline must be a non-empty string, got {self.headline!r}")


def classify_candidate_pair(
    a: CanonicalizationCandidate, b: CanonicalizationCandidate
) -> NewsCanonicalizationMethod | None:
    """Returns the STRONGEST automatic method this pair satisfies, in
    fixed precedence order (Section 21: `EXACT_CANONICAL_URL` >
    `EXACT_BODY_TEXT` > `EXACT_HEADLINE_AND_SUMMARY`), or `None` if
    none applies. Deliberately pure and side-effect-free: no I/O, no
    randomness, fully reproducible for the same two candidates."""
    if a.news_item_key == b.news_item_key:
        raise ValueError("cannot classify a candidate pair against itself")

    if a.canonical_url and b.canonical_url:
        normalized_a = normalize_canonical_url(a.canonical_url)
        normalized_b = normalize_canonical_url(b.canonical_url)
        if normalized_a is not None and normalized_a == normalized_b:
            return NewsCanonicalizationMethod.EXACT_CANONICAL_URL

    if a.body_text and b.body_text:
        normalized_body_a = normalize_text(a.body_text)
        normalized_body_b = normalize_text(b.body_text)
        if normalized_body_a == normalized_body_b and len(normalized_body_a) >= _MIN_BODY_LENGTH:
            return NewsCanonicalizationMethod.EXACT_BODY_TEXT

    if a.summary and b.summary:
        normalized_summary_a = normalize_text(a.summary)
        normalized_summary_b = normalize_text(b.summary)
        if (
            normalized_summary_a == normalized_summary_b
            and len(normalized_summary_a) >= _MIN_SUMMARY_LENGTH
            and normalize_text(a.headline) == normalize_text(b.headline)
        ):
            return NewsCanonicalizationMethod.EXACT_HEADLINE_AND_SUMMARY

    return None
