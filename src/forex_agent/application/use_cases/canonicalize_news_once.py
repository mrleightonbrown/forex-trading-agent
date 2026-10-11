"""FX-58/FX-58H: the automatic, conservative canonicalizer (`fx58_
v2`) -- one explicit, manually-invoked pass, no scheduler/daemon
(Section 33/65), performing ZERO network I/O (Section 64): it
operates exclusively on already-ingested, already-persisted evidence.

Deterministic pair order (Section 41): candidates are sorted by their
own `news_item_key` before pairing, so `itertools.combinations` over
that sorted sequence yields every pair in a fixed, reproducible
order, independent of database row order, dictionary insertion
accidents, or feed order.

`run_at` is captured EXACTLY ONCE, via the injected `clock`, and used
as `availability` for every relation decision this one run produces
(Section 8) -- never called separately per pair.

**FX-58H Section 12: review-only detection runs ONLY when the
automatic matcher found nothing.** For each pair, `classify_
candidate_pair` (AUTOMATIC: `EXACT_CANONICAL_URL`/`EXACT_BODY_TEXT`)
is tried FIRST; only if it returns `None` is `detect_review_candidate`
(the demoted headline+summary signal) consulted. A pair satisfying
BOTH an automatic rule and the review signal is reported ONLY as the
automatic match -- never additionally flagged as needing review.
Review candidates are diagnostics only: `RecordNewsCanonicalRelation`
is NEVER called for them.
"""

import itertools
from collections.abc import Callable
from dataclasses import dataclass

from forex_agent.application.ports.news_canonicalization_repository import (
    NewsCanonicalizationRepository,
)
from forex_agent.application.use_cases.record_news_canonical_relation import (
    NewsCanonicalRelationOutcome,
    RecordNewsCanonicalRelation,
)
from forex_agent.domain.news_canonical_relation_kind import NewsCanonicalRelationKind
from forex_agent.domain.news_canonicalization_matching import (
    classify_candidate_pair,
    detect_review_candidate,
)
from forex_agent.domain.news_canonicalization_method import NewsCanonicalizationMethod
from forex_agent.domain.news_canonicalization_review import NewsCanonicalizationReviewReason
from forex_agent.domain.timestamps import UtcTimestamp

ClockFn = Callable[[], UtcTimestamp]

ALGORITHM_VERSION = "fx58_v2"


def default_clock() -> UtcTimestamp:
    return UtcTimestamp.now()


@dataclass(frozen=True, slots=True)
class ProposedRelation:
    """One pair this run decided (or, under `dry_run=True`, would
    have decided) to record as `SAME_STORY` via an AUTOMATIC method
    -- enough detail for a human reviewer to inspect WITHOUT dumping
    full article bodies (FX-58 Section 42: "Do not dump full article
    bodies unnecessarily")."""

    left_news_item_key: str
    right_news_item_key: str
    left_headline: str
    right_headline: str
    left_canonical_url: str | None
    right_canonical_url: str | None
    method: NewsCanonicalizationMethod


@dataclass(frozen=True, slots=True)
class ReviewCandidate:
    """One pair flagged for HUMAN review only (FX-58H Section 4/13) --
    `RecordNewsCanonicalRelation` is never called for these; this is
    purely a reporting artifact. Never confused with `ProposedRelation`
    -- a different type, never a "proposed SAME_STORY relation"."""

    left_news_item_key: str
    right_news_item_key: str
    left_headline: str
    right_headline: str
    reason: NewsCanonicalizationReviewReason


@dataclass(frozen=True, slots=True)
class NewsCanonicalizationRunResult:
    """Factual counters for one `CanonicalizeNewsOnce` run (FX-58
    Section 66) -- no scores, no confidence percentages (Section 67).

    `headline_summary_review_candidates` (FX-58H Section 13) replaces
    the old `exact_headline_summary_matches` counter -- its name no
    longer implies a persisted match, since this signal is now
    diagnostics-only and NEVER written as a relation."""

    run_at: UtcTimestamp
    items_considered: int
    candidate_pairs: int
    relations_created: int
    relations_unchanged: int
    blocked_by_review_override: int
    exact_url_matches: int
    exact_body_matches: int
    headline_summary_review_candidates: int
    blocked_pairs: tuple[tuple[str, str], ...]
    created_relations: tuple[ProposedRelation, ...]
    review_candidates: tuple[ReviewCandidate, ...]


class CanonicalizeNewsOnce:
    """FX-58's own automatic matcher -- see the module docstring."""

    def __init__(
        self,
        repository: NewsCanonicalizationRepository,
        record: RecordNewsCanonicalRelation,
        *,
        clock: ClockFn = default_clock,
        algorithm_version: str = ALGORITHM_VERSION,
    ) -> None:
        self._repository = repository
        self._record = record
        self._clock = clock
        self._algorithm_version = algorithm_version

    async def __call__(self, *, dry_run: bool = False) -> NewsCanonicalizationRunResult:
        """`dry_run=True` (Section 65) previews exactly what a real
        run would decide and persists nothing -- see `RecordNewsCan
        onicalRelation.__call__`'s own docstring for how this is the
        SAME decision logic, never a separate implementation."""
        run_at = self._clock()
        candidates = await self._repository.list_candidates_as_of(run_at)
        sorted_candidates = tuple(sorted(candidates, key=lambda c: c.news_item_key))

        relations_created = 0
        relations_unchanged = 0
        blocked_by_review_override = 0
        exact_url_matches = 0
        exact_body_matches = 0
        headline_summary_review_candidates = 0
        blocked_pairs: list[tuple[str, str]] = []
        created_relations: list[ProposedRelation] = []
        review_candidates: list[ReviewCandidate] = []
        candidate_pairs = 0

        for a, b in itertools.combinations(sorted_candidates, 2):
            candidate_pairs += 1
            method = classify_candidate_pair(a, b)
            if method is None:
                # FX-58H Section 12: the review-only detector is
                # consulted ONLY when no automatic rule matched.
                review_reason = detect_review_candidate(a, b)
                if review_reason is not None:
                    headline_summary_review_candidates += 1
                    review_candidates.append(
                        ReviewCandidate(
                            left_news_item_key=a.news_item_key,
                            right_news_item_key=b.news_item_key,
                            left_headline=a.headline,
                            right_headline=b.headline,
                            reason=review_reason,
                        )
                    )
                # Section 5/36: the automatic matcher NEVER writes
                # NOT_SAME_STORY for a non-matching pair (review
                # candidates included), and a prior match's absence
                # today never revokes it -- simply skip, no call to
                # RecordNewsCanonicalRelation at all for either case.
                continue

            result = await self._record(
                (a.news_item_key, a.revision_sequence),
                (b.news_item_key, b.revision_sequence),
                availability=run_at,
                relation_kind=NewsCanonicalRelationKind.SAME_STORY,
                method=method,
                algorithm_version=self._algorithm_version,
                dry_run=dry_run,
            )

            if result.outcome is NewsCanonicalRelationOutcome.CREATED:
                relations_created += 1
                if method is NewsCanonicalizationMethod.EXACT_CANONICAL_URL:
                    exact_url_matches += 1
                else:
                    exact_body_matches += 1
                left, right = (a, b) if a.news_item_key == result.left_news_item_key else (b, a)
                created_relations.append(
                    ProposedRelation(
                        left_news_item_key=left.news_item_key,
                        right_news_item_key=right.news_item_key,
                        left_headline=left.headline,
                        right_headline=right.headline,
                        left_canonical_url=left.canonical_url,
                        right_canonical_url=right.canonical_url,
                        method=method,
                    )
                )
            elif result.outcome is NewsCanonicalRelationOutcome.UNCHANGED:
                relations_unchanged += 1
            elif result.outcome is NewsCanonicalRelationOutcome.BLOCKED_BY_REVIEW_OVERRIDE:
                blocked_by_review_override += 1
                blocked_pairs.append((result.left_news_item_key, result.right_news_item_key))

        return NewsCanonicalizationRunResult(
            run_at=run_at,
            items_considered=len(sorted_candidates),
            candidate_pairs=candidate_pairs,
            relations_created=relations_created,
            relations_unchanged=relations_unchanged,
            blocked_by_review_override=blocked_by_review_override,
            exact_url_matches=exact_url_matches,
            exact_body_matches=exact_body_matches,
            headline_summary_review_candidates=headline_summary_review_candidates,
            blocked_pairs=tuple(blocked_pairs),
            created_relations=tuple(created_relations),
            review_candidates=tuple(review_candidates),
        )
