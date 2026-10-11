"""FX-58 Section 59: fast, DB-free unit tests for `CanonicalizeNewsOnce`
against an in-memory fake repository."""

from datetime import UTC, datetime

import pytest

from forex_agent.application.ports.news_canonicalization_repository import (
    NewsCanonicalRelationConflictError,
    RelationVintageWriteResult,
)
from forex_agent.application.use_cases.canonicalize_news_once import CanonicalizeNewsOnce
from forex_agent.application.use_cases.record_news_canonical_relation import (
    RecordNewsCanonicalRelation,
)
from forex_agent.domain.news_canonical_relation_kind import NewsCanonicalRelationKind
from forex_agent.domain.news_canonical_relation_vintage import NewsCanonicalRelationVintage
from forex_agent.domain.news_canonicalization_matching import CanonicalizationCandidate
from forex_agent.domain.news_canonicalization_method import NewsCanonicalizationMethod
from forex_agent.domain.news_item import NewsItem
from forex_agent.domain.timestamps import UtcTimestamp

_TS = UtcTimestamp(datetime(2026, 1, 1, tzinfo=UTC))


def _candidate(
    key: str,
    *,
    headline: str = "A headline",
    summary: str | None = None,
    body_text: str | None = None,
    canonical_url: str | None = None,
) -> CanonicalizationCandidate:
    return CanonicalizationCandidate(
        news_item_key=key,
        first_seen_at=_TS,
        revision_sequence=0,
        availability=_TS,
        headline=headline,
        summary=summary,
        body_text=body_text,
        canonical_url=canonical_url,
    )


class FakeNewsCanonicalizationRepository:
    """Full in-memory implementation of `NewsCanonicalizationRepository`
    -- `list_candidates_as_of` returns a pre-seeded, fixed candidate
    set regardless of `as_of` (deterministic for these unit tests)."""

    def __init__(self, candidates: tuple[CanonicalizationCandidate, ...]) -> None:
        self._candidates = candidates
        self._relations: dict[tuple[str, str], list[NewsCanonicalRelationVintage]] = {}

    async def list_candidates_as_of(
        self, as_of: UtcTimestamp, *, include_backfill: bool = False
    ) -> tuple[CanonicalizationCandidate, ...]:
        return self._candidates

    async def list_items_seen_as_of(self, as_of: UtcTimestamp) -> tuple[NewsItem, ...]:
        raise NotImplementedError("not used by CanonicalizeNewsOnce")

    async def list_relation_vintages_for_pair(
        self, left_news_item_key: str, right_news_item_key: str
    ) -> tuple[NewsCanonicalRelationVintage, ...]:
        return tuple(self._relations.get((left_news_item_key, right_news_item_key), []))

    async def list_latest_relation_states_as_of(
        self, as_of: UtcTimestamp
    ) -> tuple[NewsCanonicalRelationVintage, ...]:
        raise NotImplementedError("not used by CanonicalizeNewsOnce")

    async def latest_relation_for_pair(
        self, left_news_item_key: str, right_news_item_key: str
    ) -> NewsCanonicalRelationVintage | None:
        rows = self._relations.get((left_news_item_key, right_news_item_key), [])
        if not rows:
            return None
        return max(rows, key=lambda r: (r.availability.value, r.revision_sequence))

    async def latest_relation_as_of(
        self, left_news_item_key: str, right_news_item_key: str, as_of: UtcTimestamp
    ) -> NewsCanonicalRelationVintage | None:
        rows = [
            r
            for r in self._relations.get((left_news_item_key, right_news_item_key), [])
            if r.availability.value <= as_of.value
        ]
        if not rows:
            return None
        return max(rows, key=lambda r: (r.availability.value, r.revision_sequence))

    async def add_relation_vintage(
        self, vintage: NewsCanonicalRelationVintage
    ) -> RelationVintageWriteResult:
        key = (vintage.left_news_item_key, vintage.right_news_item_key)
        rows = self._relations.setdefault(key, [])
        for existing in rows:
            if existing.revision_sequence == vintage.revision_sequence:
                if existing == vintage:
                    return RelationVintageWriteResult(inserted=False)
                raise NewsCanonicalRelationConflictError(existing, vintage)
        rows.append(vintage)
        return RelationVintageWriteResult(inserted=True)


def _ts(hour: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, hour, tzinfo=UTC))


@pytest.mark.asyncio
async def test_run_clock_is_captured_exactly_once() -> None:
    repo = FakeNewsCanonicalizationRepository(
        (_candidate("a", canonical_url="https://x.com/1"), _candidate("b"))
    )
    call_count = 0

    def clock() -> UtcTimestamp:
        nonlocal call_count
        call_count += 1
        return _ts(10)

    canonicalize = CanonicalizeNewsOnce(repo, RecordNewsCanonicalRelation(repo), clock=clock)
    await canonicalize()

    assert call_count == 1


@pytest.mark.asyncio
async def test_exact_pair_writes_one_same_story_revision() -> None:
    repo = FakeNewsCanonicalizationRepository(
        (
            _candidate("a", canonical_url="https://x.com/1"),
            _candidate("b", canonical_url="https://x.com/1"),
        )
    )
    canonicalize = CanonicalizeNewsOnce(
        repo, RecordNewsCanonicalRelation(repo), clock=lambda: _ts(10)
    )

    result = await canonicalize()

    assert result.items_considered == 2
    assert result.candidate_pairs == 1
    assert result.relations_created == 1
    assert result.exact_url_matches == 1
    relations = await repo.list_relation_vintages_for_pair("a", "b")
    assert len(relations) == 1
    assert relations[0].availability == _ts(10)


@pytest.mark.asyncio
async def test_second_identical_run_writes_nothing() -> None:
    repo = FakeNewsCanonicalizationRepository(
        (
            _candidate("a", canonical_url="https://x.com/1"),
            _candidate("b", canonical_url="https://x.com/1"),
        )
    )
    canonicalize = CanonicalizeNewsOnce(
        repo, RecordNewsCanonicalRelation(repo), clock=lambda: _ts(10)
    )
    await canonicalize()

    second = CanonicalizeNewsOnce(repo, RecordNewsCanonicalRelation(repo), clock=lambda: _ts(11))
    result = await second()

    assert result.relations_created == 0
    assert result.relations_unchanged == 1


@pytest.mark.asyncio
async def test_no_match_pair_writes_nothing() -> None:
    repo = FakeNewsCanonicalizationRepository(
        (_candidate("a", headline="Headline A"), _candidate("b", headline="Headline B"))
    )
    canonicalize = CanonicalizeNewsOnce(
        repo, RecordNewsCanonicalRelation(repo), clock=lambda: _ts(10)
    )

    result = await canonicalize()

    assert result.relations_created == 0
    assert result.candidate_pairs == 1
    relations = await repo.list_relation_vintages_for_pair("a", "b")
    assert relations == ()


@pytest.mark.asyncio
async def test_existing_not_same_story_blocks_auto_override_and_is_counted() -> None:
    repo = FakeNewsCanonicalizationRepository(
        (
            _candidate("a", canonical_url="https://x.com/1"),
            _candidate("b", canonical_url="https://x.com/1"),
        )
    )
    record = RecordNewsCanonicalRelation(repo)

    await record(
        ("a", 0),
        ("b", 0),
        availability=_ts(5),
        relation_kind=NewsCanonicalRelationKind.NOT_SAME_STORY,
        method=NewsCanonicalizationMethod.MANUAL_REVIEW,
        algorithm_version="fx58_v1",
    )

    canonicalize = CanonicalizeNewsOnce(repo, record, clock=lambda: _ts(10))
    result = await canonicalize()

    assert result.relations_created == 0
    assert result.blocked_by_review_override == 1
    assert result.blocked_pairs == (("a", "b"),)


@pytest.mark.asyncio
async def test_relation_disappearance_does_not_create_not_same_story() -> None:
    # T1: body matches (>=200 chars) -- SAME_STORY recorded.
    body = "x" * 200
    repo = FakeNewsCanonicalizationRepository(
        (_candidate("a", body_text=body), _candidate("b", body_text=body))
    )
    record = RecordNewsCanonicalRelation(repo)
    first = CanonicalizeNewsOnce(repo, record, clock=lambda: _ts(10))
    await first()

    # T2: "a"'s body no longer matches -- a fresh repo reflecting the
    # NEW (non-matching) candidate state, but with the EXISTING
    # relation carried over.
    repo2 = FakeNewsCanonicalizationRepository(
        (
            _candidate("a", body_text="a completely different body" * 10),
            _candidate("b", body_text=body),
        )
    )
    repo2._relations = repo._relations  # same underlying relation store
    second = CanonicalizeNewsOnce(repo2, RecordNewsCanonicalRelation(repo2), clock=lambda: _ts(11))
    result = await second()

    assert result.relations_created == 0
    relations = await repo2.list_relation_vintages_for_pair("a", "b")
    assert len(relations) == 1  # still just the original SAME_STORY -- never a NOT_SAME_STORY


@pytest.mark.asyncio
async def test_multiple_matching_methods_create_one_relation_strongest_wins() -> None:
    body = "x" * 200
    summary = "s" * 80
    repo = FakeNewsCanonicalizationRepository(
        (
            _candidate(
                "a",
                headline="Same Headline",
                summary=summary,
                body_text=body,
                canonical_url="https://x.com/1",
            ),
            _candidate(
                "b",
                headline="Same Headline",
                summary=summary,
                body_text=body,
                canonical_url="https://x.com/1",
            ),
        )
    )
    canonicalize = CanonicalizeNewsOnce(
        repo, RecordNewsCanonicalRelation(repo), clock=lambda: _ts(10)
    )

    result = await canonicalize()

    assert result.relations_created == 1
    assert result.exact_url_matches == 1
    assert result.exact_body_matches == 0
    assert result.exact_headline_summary_matches == 0


@pytest.mark.asyncio
async def test_deterministic_pair_order_independent_of_candidate_input_order() -> None:
    forward = FakeNewsCanonicalizationRepository((_candidate("z"), _candidate("a")))
    reversed_ = FakeNewsCanonicalizationRepository((_candidate("a"), _candidate("z")))

    result_forward = await CanonicalizeNewsOnce(
        forward, RecordNewsCanonicalRelation(forward), clock=lambda: _ts(10)
    )()
    result_reversed = await CanonicalizeNewsOnce(
        reversed_, RecordNewsCanonicalRelation(reversed_), clock=lambda: _ts(10)
    )()

    assert result_forward.candidate_pairs == result_reversed.candidate_pairs == 1


@pytest.mark.asyncio
async def test_dry_run_persists_nothing_but_reports_the_same_match() -> None:
    repo = FakeNewsCanonicalizationRepository(
        (
            _candidate("a", canonical_url="https://x.com/1"),
            _candidate("b", canonical_url="https://x.com/1"),
        )
    )
    canonicalize = CanonicalizeNewsOnce(
        repo, RecordNewsCanonicalRelation(repo), clock=lambda: _ts(10)
    )

    result = await canonicalize(dry_run=True)

    assert result.relations_created == 1
    assert len(result.created_relations) == 1
    relations = await repo.list_relation_vintages_for_pair("a", "b")
    assert relations == ()  # nothing actually persisted


@pytest.mark.asyncio
async def test_basis_vintage_revision_sequences_are_the_actual_compared_ones() -> None:
    a = CanonicalizationCandidate(
        news_item_key="a",
        first_seen_at=_TS,
        revision_sequence=3,
        availability=_TS,
        headline="H",
        summary=None,
        body_text=None,
        canonical_url="https://x.com/1",
    )
    b = CanonicalizationCandidate(
        news_item_key="b",
        first_seen_at=_TS,
        revision_sequence=7,
        availability=_TS,
        headline="H2",
        summary=None,
        body_text=None,
        canonical_url="https://x.com/1",
    )
    repo = FakeNewsCanonicalizationRepository((a, b))
    canonicalize = CanonicalizeNewsOnce(
        repo, RecordNewsCanonicalRelation(repo), clock=lambda: _ts(10)
    )

    await canonicalize()

    relation = await repo.latest_relation_for_pair("a", "b")
    assert relation is not None
    assert relation.left_item_revision_sequence == 3
    assert relation.right_item_revision_sequence == 7
