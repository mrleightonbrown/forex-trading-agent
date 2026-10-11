"""FX-58: fast, DB-free unit tests for `RecordNewsCanonicalRelation`
against an in-memory fake repository -- complements the live-Postgres
integration suite in `tests/integration/test_news_canonicalization_
repository.py`."""

from datetime import UTC, datetime

import pytest

from forex_agent.application.ports.news_canonicalization_repository import (
    NewsCanonicalRelationConflictError,
    RelationVintageWriteResult,
)
from forex_agent.application.use_cases.record_news_canonical_relation import (
    NewsCanonicalRelationOutcome,
    OutOfOrderRelationDecisionError,
    RecordNewsCanonicalRelation,
    SelfNewsCanonicalRelationError,
)
from forex_agent.domain.news_canonical_relation_kind import NewsCanonicalRelationKind
from forex_agent.domain.news_canonical_relation_vintage import NewsCanonicalRelationVintage
from forex_agent.domain.news_canonicalization_matching import CanonicalizationCandidate
from forex_agent.domain.news_canonicalization_method import NewsCanonicalizationMethod
from forex_agent.domain.news_item import NewsItem
from forex_agent.domain.timestamps import UtcTimestamp


class FakeNewsCanonicalizationRepository:
    """In-memory implementation of the FULL `NewsCanonicalization
    Repository` Protocol -- `RecordNewsCanonicalRelation` itself only
    ever calls `latest_relation_for_pair`/`add_relation_vintage`, but
    every method is implemented so this fake structurally proves the
    full Protocol contract, mirroring `FakeNewsRepository`'s own
    precedent in `test_record_news_observation.py`."""

    def __init__(self, *, simulate_lost_race: bool = False) -> None:
        self._relations: dict[tuple[str, str], list[NewsCanonicalRelationVintage]] = {}
        # FX-58H Section 18/19: when True, `add_relation_vintage`
        # reports `inserted=False` for the FIRST write of any given
        # identity, simulating a concurrent writer that already
        # durably inserted the exact same payload moments earlier --
        # without needing a real second session/thread for this fast,
        # DB-free unit test.
        self._simulate_lost_race = simulate_lost_race

    async def list_candidates_as_of(
        self, as_of: UtcTimestamp, *, include_backfill: bool = False
    ) -> tuple[CanonicalizationCandidate, ...]:
        raise NotImplementedError("not used by RecordNewsCanonicalRelation")

    async def list_items_seen_as_of(self, as_of: UtcTimestamp) -> tuple[NewsItem, ...]:
        raise NotImplementedError("not used by RecordNewsCanonicalRelation")

    async def list_relation_vintages_for_pair(
        self, left_news_item_key: str, right_news_item_key: str
    ) -> tuple[NewsCanonicalRelationVintage, ...]:
        return tuple(self._relations.get((left_news_item_key, right_news_item_key), []))

    async def list_latest_relation_states_as_of(
        self, as_of: UtcTimestamp
    ) -> tuple[NewsCanonicalRelationVintage, ...]:
        raise NotImplementedError("not used by RecordNewsCanonicalRelation")

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
        if self._simulate_lost_race:
            return RelationVintageWriteResult(inserted=False)
        return RelationVintageWriteResult(inserted=True)


def _ts(hour: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, hour, tzinfo=UTC))


@pytest.mark.asyncio
async def test_first_decision_creates_revision_zero() -> None:
    repo = FakeNewsCanonicalizationRepository()
    record = RecordNewsCanonicalRelation(repo)

    result = await record(
        ("B", 0),
        ("A", 0),
        availability=_ts(10),
        relation_kind=NewsCanonicalRelationKind.SAME_STORY,
        method=NewsCanonicalizationMethod.EXACT_CANONICAL_URL,
        algorithm_version="fx58_v1",
    )

    assert result.outcome is NewsCanonicalRelationOutcome.CREATED
    # Caller passed (B, A) -- canonical ordering must still resolve to (A, B).
    assert result.left_news_item_key == "A"
    assert result.right_news_item_key == "B"
    assert result.relation.revision_sequence == 0


@pytest.mark.asyncio
async def test_pair_order_from_caller_does_not_matter() -> None:
    repo = FakeNewsCanonicalizationRepository()
    record = RecordNewsCanonicalRelation(repo)

    result = await record(
        ("A", 3),
        ("B", 7),
        availability=_ts(10),
        relation_kind=NewsCanonicalRelationKind.SAME_STORY,
        method=NewsCanonicalizationMethod.EXACT_CANONICAL_URL,
        algorithm_version="fx58_v1",
    )

    assert result.relation.left_item_revision_sequence == 3
    assert result.relation.right_item_revision_sequence == 7


@pytest.mark.asyncio
async def test_self_pair_raises() -> None:
    repo = FakeNewsCanonicalizationRepository()
    record = RecordNewsCanonicalRelation(repo)

    with pytest.raises(SelfNewsCanonicalRelationError):
        await record(
            ("A", 0),
            ("A", 1),
            availability=_ts(10),
            relation_kind=NewsCanonicalRelationKind.SAME_STORY,
            method=NewsCanonicalizationMethod.EXACT_CANONICAL_URL,
            algorithm_version="fx58_v1",
        )


@pytest.mark.asyncio
async def test_second_identical_decision_is_unchanged_mints_no_new_revision() -> None:
    repo = FakeNewsCanonicalizationRepository()
    record = RecordNewsCanonicalRelation(repo)

    await record(
        ("A", 0),
        ("B", 0),
        availability=_ts(10),
        relation_kind=NewsCanonicalRelationKind.SAME_STORY,
        method=NewsCanonicalizationMethod.EXACT_CANONICAL_URL,
        algorithm_version="fx58_v1",
    )
    second = await record(
        ("A", 1),
        ("B", 1),
        availability=_ts(11),
        relation_kind=NewsCanonicalRelationKind.SAME_STORY,
        method=NewsCanonicalizationMethod.EXACT_BODY_TEXT,  # a DIFFERENT method
        algorithm_version="fx58_v1",
    )

    assert second.outcome is NewsCanonicalRelationOutcome.UNCHANGED
    # The original decision is preserved untouched -- method/basis
    # sequences/availability all still reflect the FIRST decision.
    assert second.relation.method is NewsCanonicalizationMethod.EXACT_CANONICAL_URL
    assert second.relation.availability == _ts(10)
    assert second.relation.revision_sequence == 0


@pytest.mark.asyncio
async def test_out_of_order_decision_raises() -> None:
    repo = FakeNewsCanonicalizationRepository()
    record = RecordNewsCanonicalRelation(repo)

    await record(
        ("A", 0),
        ("B", 0),
        availability=_ts(10),
        relation_kind=NewsCanonicalRelationKind.SAME_STORY,
        method=NewsCanonicalizationMethod.EXACT_CANONICAL_URL,
        algorithm_version="fx58_v1",
    )

    with pytest.raises(OutOfOrderRelationDecisionError):
        await record(
            ("A", 0),
            ("B", 0),
            availability=_ts(9),
            relation_kind=NewsCanonicalRelationKind.SAME_STORY,
            method=NewsCanonicalizationMethod.EXACT_CANONICAL_URL,
            algorithm_version="fx58_v1",
        )


@pytest.mark.asyncio
async def test_equal_availability_is_allowed() -> None:
    repo = FakeNewsCanonicalizationRepository()
    record = RecordNewsCanonicalRelation(repo)

    await record(
        ("A", 0),
        ("B", 0),
        availability=_ts(10),
        relation_kind=NewsCanonicalRelationKind.SAME_STORY,
        method=NewsCanonicalizationMethod.EXACT_CANONICAL_URL,
        algorithm_version="fx58_v1",
    )
    # Equal availability, but a genuinely different decision (manual
    # review correcting to NOT_SAME_STORY) -- must not raise on
    # ordering grounds; equal is explicitly permitted.
    result = await record(
        ("A", 0),
        ("B", 0),
        availability=_ts(10),
        relation_kind=NewsCanonicalRelationKind.NOT_SAME_STORY,
        method=NewsCanonicalizationMethod.MANUAL_REVIEW,
        algorithm_version="fx58_v1",
    )
    assert result.outcome is NewsCanonicalRelationOutcome.REVISION_ADDED


@pytest.mark.asyncio
async def test_existing_not_same_story_blocks_automatic_override() -> None:
    repo = FakeNewsCanonicalizationRepository()
    record = RecordNewsCanonicalRelation(repo)

    # Seed a reviewed NOT_SAME_STORY correction.
    await record(
        ("A", 0),
        ("B", 0),
        availability=_ts(10),
        relation_kind=NewsCanonicalRelationKind.SAME_STORY,
        method=NewsCanonicalizationMethod.EXACT_CANONICAL_URL,
        algorithm_version="fx58_v1",
    )
    await record(
        ("A", 0),
        ("B", 0),
        availability=_ts(11),
        relation_kind=NewsCanonicalRelationKind.NOT_SAME_STORY,
        method=NewsCanonicalizationMethod.MANUAL_REVIEW,
        algorithm_version="fx58_v1",
    )

    # The automatic matcher sees it again later -- must be blocked,
    # never silently overturning the reviewed correction.
    result = await record(
        ("A", 2),
        ("B", 2),
        availability=_ts(12),
        relation_kind=NewsCanonicalRelationKind.SAME_STORY,
        method=NewsCanonicalizationMethod.EXACT_BODY_TEXT,
        algorithm_version="fx58_v1",
    )
    assert result.outcome is NewsCanonicalRelationOutcome.BLOCKED_BY_REVIEW_OVERRIDE
    assert result.relation.relation_kind is NewsCanonicalRelationKind.NOT_SAME_STORY


@pytest.mark.asyncio
async def test_manual_review_may_still_reverse_not_same_story() -> None:
    # Only an explicit MANUAL_REVIEW may reverse a reviewed decision
    # (Section 35's own "only an explicit future manual review").
    repo = FakeNewsCanonicalizationRepository()
    record = RecordNewsCanonicalRelation(repo)

    await record(
        ("A", 0),
        ("B", 0),
        availability=_ts(10),
        relation_kind=NewsCanonicalRelationKind.NOT_SAME_STORY,
        method=NewsCanonicalizationMethod.MANUAL_REVIEW,
        algorithm_version="fx58_v1",
    )
    result = await record(
        ("A", 1),
        ("B", 1),
        availability=_ts(11),
        relation_kind=NewsCanonicalRelationKind.SAME_STORY,
        method=NewsCanonicalizationMethod.MANUAL_REVIEW,
        algorithm_version="fx58_v1",
    )
    assert result.outcome is NewsCanonicalRelationOutcome.REVISION_ADDED
    assert result.relation.relation_kind is NewsCanonicalRelationKind.SAME_STORY


# --- FX-58H Section 18: outcome reflects the actual durable write ---------


@pytest.mark.asyncio
async def test_lost_race_on_first_creation_reports_unchanged_not_created() -> None:
    # A concurrent writer already durably inserted the EXACT SAME
    # revision-0 payload first -- this caller's own `add_relation_
    # vintage` call returns inserted=False, so the outcome must be
    # UNCHANGED, never CREATED (the bug this hardening pass fixes).
    repo = FakeNewsCanonicalizationRepository(simulate_lost_race=True)
    record = RecordNewsCanonicalRelation(repo)

    result = await record(
        ("A", 0),
        ("B", 0),
        availability=_ts(10),
        relation_kind=NewsCanonicalRelationKind.SAME_STORY,
        method=NewsCanonicalizationMethod.EXACT_CANONICAL_URL,
        algorithm_version="fx58_v2",
    )

    assert result.outcome is NewsCanonicalRelationOutcome.UNCHANGED
    # Exactly one durable row exists regardless of how this caller's
    # own attempt was reported.
    stored = await repo.list_relation_vintages_for_pair("A", "B")
    assert len(stored) == 1


@pytest.mark.asyncio
async def test_lost_race_on_later_revision_reports_unchanged_not_revision_added() -> None:
    repo = FakeNewsCanonicalizationRepository()
    record = RecordNewsCanonicalRelation(repo)
    await record(
        ("A", 0),
        ("B", 0),
        availability=_ts(10),
        relation_kind=NewsCanonicalRelationKind.SAME_STORY,
        method=NewsCanonicalizationMethod.EXACT_CANONICAL_URL,
        algorithm_version="fx58_v2",
    )
    # From here on, simulate every subsequent write losing its own race.
    repo._simulate_lost_race = True

    result = await record(
        ("A", 1),
        ("B", 1),
        availability=_ts(11),
        relation_kind=NewsCanonicalRelationKind.NOT_SAME_STORY,
        method=NewsCanonicalizationMethod.MANUAL_REVIEW,
        algorithm_version="fx58_v2",
    )

    assert result.outcome is NewsCanonicalRelationOutcome.UNCHANGED
    stored = await repo.list_relation_vintages_for_pair("A", "B")
    assert len(stored) == 2  # revision 0 and revision 1 both durably exist


@pytest.mark.asyncio
async def test_relation_revision_example_section_37() -> None:
    # T1: SAME_STORY @ 10:00. T2: MANUAL_REVIEW -> NOT_SAME_STORY @ 11:00.
    repo = FakeNewsCanonicalizationRepository()
    record = RecordNewsCanonicalRelation(repo)

    await record(
        ("A", 0),
        ("B", 0),
        availability=_ts(10),
        relation_kind=NewsCanonicalRelationKind.SAME_STORY,
        method=NewsCanonicalizationMethod.EXACT_CANONICAL_URL,
        algorithm_version="fx58_v1",
    )
    await record(
        ("A", 1),
        ("B", 1),
        availability=_ts(11),
        relation_kind=NewsCanonicalRelationKind.NOT_SAME_STORY,
        method=NewsCanonicalizationMethod.MANUAL_REVIEW,
        algorithm_version="fx58_v1",
    )

    as_of_1030 = UtcTimestamp(datetime(2026, 1, 1, 10, 30, tzinfo=UTC))
    as_of_1130 = UtcTimestamp(datetime(2026, 1, 1, 11, 30, tzinfo=UTC))
    at_1030 = await repo.latest_relation_as_of("A", "B", as_of_1030)
    at_1130 = await repo.latest_relation_as_of("A", "B", as_of_1130)
    assert at_1030 is not None
    assert at_1030.relation_kind is NewsCanonicalRelationKind.SAME_STORY
    assert at_1130 is not None
    assert at_1130.relation_kind is NewsCanonicalRelationKind.NOT_SAME_STORY
