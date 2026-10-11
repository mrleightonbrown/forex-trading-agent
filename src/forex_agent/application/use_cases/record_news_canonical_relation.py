"""FX-58: append-only recording of one canonical-relation decision,
following `RecordNewsObservation`'s own established shape (FX-58
Section 31) -- compare the latest stored state for a pair, and only
append a new revision when the semantic decision genuinely changes.

**Precedence, mirroring FX-56H.1's own corrected lesson ("check
ordering FIRST, unconditionally, THEN check identity")**: PIT
ordering is checked before anything else. An incoming decision whose
`availability` is EARLIER than the pair's own latest recorded
relation always raises `OutOfOrderRelationDecisionError`, regardless
of whether the decision itself would otherwise be a no-op (Section
32) -- an earlier `availability` is itself an assertion about when
FTA made this decision, and that assertion must be rejected
regardless of content. Equal `availability` is explicitly permitted.

**The automatic matcher may never overturn a reviewed `NOT_SAME_
STORY` (Section 35).** If the pair's latest relation is `NOT_SAME_
STORY` and the incoming decision uses an AUTOMATIC method (anything
other than `MANUAL_REVIEW`), this use case returns `BLOCKED_BY_
REVIEW_OVERRIDE` and writes nothing -- never raises, since this is an
ordinary, expected outcome for `CanonicalizeNewsOnce` to count and
report, not a bug.
"""

from dataclasses import dataclass
from enum import Enum

from forex_agent.application.ports.news_canonicalization_repository import (
    NewsCanonicalizationRepository,
)
from forex_agent.domain.news_canonical_relation_kind import NewsCanonicalRelationKind
from forex_agent.domain.news_canonical_relation_vintage import NewsCanonicalRelationVintage
from forex_agent.domain.news_canonicalization_method import NewsCanonicalizationMethod
from forex_agent.domain.timestamps import UtcTimestamp

_AUTOMATIC_METHODS = (
    NewsCanonicalizationMethod.EXACT_CANONICAL_URL,
    NewsCanonicalizationMethod.EXACT_BODY_TEXT,
    NewsCanonicalizationMethod.EXACT_HEADLINE_AND_SUMMARY,
)


class NewsCanonicalRelationOutcome(Enum):
    """What `RecordNewsCanonicalRelation` actually did for one pair
    decision (FX-58 Section 31/34/35)."""

    CREATED = "CREATED"
    REVISION_ADDED = "REVISION_ADDED"
    UNCHANGED = "UNCHANGED"
    BLOCKED_BY_REVIEW_OVERRIDE = "BLOCKED_BY_REVIEW_OVERRIDE"


@dataclass(frozen=True, slots=True)
class NewsCanonicalRelationRecordResult:
    left_news_item_key: str
    right_news_item_key: str
    outcome: NewsCanonicalRelationOutcome
    relation: NewsCanonicalRelationVintage
    """The relevant relation after this call: the newly-written one
    for `CREATED`/`REVISION_ADDED`, or the EXISTING one for
    `UNCHANGED`/`BLOCKED_BY_REVIEW_OVERRIDE`."""


class SelfNewsCanonicalRelationError(Exception):
    """Raised when both sides of a proposed relation name the SAME
    `news_item_key` -- a self-relation is forbidden (FX-58 Section 4)."""

    def __init__(self, news_item_key: str) -> None:
        self.news_item_key = news_item_key
        super().__init__(f"cannot record a canonical relation of {news_item_key!r} to itself")


class OutOfOrderRelationDecisionError(Exception):
    """Raised when an incoming relation decision claims an
    `availability` earlier than the pair's own latest recorded
    relation (FX-58 Section 32) -- refusing to append a backdated
    canonicalization decision, regardless of whether its own content
    would otherwise be a no-op change."""

    def __init__(
        self,
        left_news_item_key: str,
        right_news_item_key: str,
        latest_availability: UtcTimestamp,
        incoming_availability: UtcTimestamp,
    ) -> None:
        self.left_news_item_key = left_news_item_key
        self.right_news_item_key = right_news_item_key
        self.latest_availability = latest_availability
        self.incoming_availability = incoming_availability
        super().__init__(
            f"canonical relation for pair (left={left_news_item_key!r}, "
            f"right={right_news_item_key!r}) claims availability="
            f"{incoming_availability.value.isoformat()}, earlier than the latest recorded "
            f"relation's own availability={latest_availability.value.isoformat()} -- refusing "
            "to append a backdated canonicalization decision"
        )


class RecordNewsCanonicalRelation:
    """FX-58's own append-only canonical-relation-recording use case
    -- see the module docstring."""

    def __init__(self, repository: NewsCanonicalizationRepository) -> None:
        self._repository = repository

    async def __call__(
        self,
        item_a: tuple[str, int],
        item_b: tuple[str, int],
        availability: UtcTimestamp,
        relation_kind: NewsCanonicalRelationKind,
        method: NewsCanonicalizationMethod,
        algorithm_version: str,
        *,
        dry_run: bool = False,
    ) -> NewsCanonicalRelationRecordResult:
        """`item_a`/`item_b` are each `(news_item_key, item_revision_
        sequence)` -- the caller need not pre-sort them into left/
        right order; this method canonicalizes the pair itself
        (Section 4) and swaps the two basis revision sequences to
        match.

        `dry_run=True` (FX-58 Section 65) computes and returns the
        EXACT SAME outcome/relation a real call would, using the
        EXACT SAME decision logic below, but never calls `self._
        repository.add_relation_vintage` -- so `scripts/canonicalize_
        news.py --dry-run` previews real decisions with zero
        persistence, never a separate, divergent preview
        implementation."""
        news_item_key_a, revision_sequence_a = item_a
        news_item_key_b, revision_sequence_b = item_b
        if news_item_key_a == news_item_key_b:
            raise SelfNewsCanonicalRelationError(news_item_key_a)

        if news_item_key_a < news_item_key_b:
            left_key, left_revision = news_item_key_a, revision_sequence_a
            right_key, right_revision = news_item_key_b, revision_sequence_b
        else:
            left_key, left_revision = news_item_key_b, revision_sequence_b
            right_key, right_revision = news_item_key_a, revision_sequence_a

        latest = await self._repository.latest_relation_for_pair(left_key, right_key)

        if latest is None:
            created = NewsCanonicalRelationVintage(
                left_news_item_key=left_key,
                right_news_item_key=right_key,
                revision_sequence=0,
                availability=availability,
                relation_kind=relation_kind,
                method=method,
                left_item_revision_sequence=left_revision,
                right_item_revision_sequence=right_revision,
                algorithm_version=algorithm_version,
            )
            if not dry_run:
                await self._repository.add_relation_vintage(created)
            return NewsCanonicalRelationRecordResult(
                left_key, right_key, NewsCanonicalRelationOutcome.CREATED, created
            )

        if availability.value < latest.availability.value:
            raise OutOfOrderRelationDecisionError(
                left_key, right_key, latest.availability, availability
            )

        if latest.relation_kind is NewsCanonicalRelationKind.NOT_SAME_STORY and method in (
            _AUTOMATIC_METHODS
        ):
            return NewsCanonicalRelationRecordResult(
                left_key, right_key, NewsCanonicalRelationOutcome.BLOCKED_BY_REVIEW_OVERRIDE, latest
            )

        if latest.relation_kind is relation_kind:
            # FX-58 Section 34: re-observing the SAME decision (even
            # via a different method, or after an unrelated vintage
            # change) is UNCHANGED -- the original relation already
            # records when FTA first learned this dedup fact.
            return NewsCanonicalRelationRecordResult(
                left_key, right_key, NewsCanonicalRelationOutcome.UNCHANGED, latest
            )

        revised = NewsCanonicalRelationVintage(
            left_news_item_key=left_key,
            right_news_item_key=right_key,
            revision_sequence=latest.revision_sequence + 1,
            availability=availability,
            relation_kind=relation_kind,
            method=method,
            left_item_revision_sequence=left_revision,
            right_item_revision_sequence=right_revision,
            algorithm_version=algorithm_version,
        )
        if not dry_run:
            await self._repository.add_relation_vintage(revised)
        return NewsCanonicalRelationRecordResult(
            left_key, right_key, NewsCanonicalRelationOutcome.REVISION_ADDED, revised
        )
