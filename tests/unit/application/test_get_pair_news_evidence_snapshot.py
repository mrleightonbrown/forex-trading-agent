"""FX-60: fast, DB-free unit tests for `GetPairNewsEvidenceSnapshot`
against in-memory fakes -- complements the live-Postgres end-to-end
suite in `tests/integration/test_pair_news_evidence_snapshot.py`,
which is the authoritative source for the mandatory PIT worked
examples (Sections 58-73)."""

import dataclasses
import pathlib
from datetime import UTC, datetime

import pytest

from forex_agent.application.ports.news_repository import (
    NewsVintageWriteOutcome,
)
from forex_agent.application.use_cases.get_news_semantic_state_as_of import NewsSemanticState
from forex_agent.application.use_cases.get_pair_news_evidence_snapshot import (
    SNAPSHOT_POLICY_VERSION,
    GetPairNewsEvidenceSnapshot,
    NewsPairEvidenceGroup,
    NewsPairEvidenceMember,
    NewsPairEvidenceSnapshot,
    NewsPairSemanticCoverage,
    NewsPairSnapshotAccounting,
    NewsPairSnapshotConstructionError,
)
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.news_canonical_relation_kind import NewsCanonicalRelationKind
from forex_agent.domain.news_canonical_relation_vintage import NewsCanonicalRelationVintage
from forex_agent.domain.news_canonicalization_method import NewsCanonicalizationMethod
from forex_agent.domain.news_currency_relevance import NewsCurrencyRelevance
from forex_agent.domain.news_currency_relevance_reason import NewsCurrencyRelevanceReason
from forex_agent.domain.news_entity_annotation import NewsEntityAnnotation
from forex_agent.domain.news_entity_evidence_kind import NewsEntityEvidenceKind
from forex_agent.domain.news_entity_type import NewsEntityType
from forex_agent.domain.news_evidence_disposition import NewsEvidenceDisposition
from forex_agent.domain.news_item import NewsItem
from forex_agent.domain.news_item_vintage import NewsItemVintage
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.news_pair_relevance import NewsPairRelevanceSide
from forex_agent.domain.news_semantic_annotation_vintage import NewsSemanticAnnotationVintage
from forex_agent.domain.news_semantic_classification import NewsSemanticClassification
from forex_agent.domain.news_source_identity import NewsSourceIdentity
from forex_agent.domain.news_source_status import NewsSourceStatus
from forex_agent.domain.news_topic import NewsTopic
from forex_agent.domain.news_topic_annotation import NewsTopicAnnotation
from forex_agent.domain.timestamps import UtcTimestamp

EURUSD = Instrument(base_currency="EUR", quote_currency="USD")


def _ts(hour: int, minute: int = 0) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, hour, minute, tzinfo=UTC))


class FakeWorld:
    """One shared in-memory evidence store, backing all three fakes
    below -- mirrors how a single Postgres database backs all three
    real repositories in production."""

    def __init__(self) -> None:
        self.items: dict[str, NewsItem] = {}
        self.vintages: dict[str, list[NewsItemVintage]] = {}
        self.relations: list[NewsCanonicalRelationVintage] = []
        self.annotations: dict[str, list[NewsSemanticAnnotationVintage]] = {}

    def add_item(
        self,
        news_item_key: str,
        *,
        first_seen_at: UtcTimestamp,
        headline: str = "H",
        source_status: NewsSourceStatus = NewsSourceStatus.ACTIVE,
        evidence_disposition: NewsEvidenceDisposition = NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
        observation_mode: NewsObservationMode = NewsObservationMode.PROSPECTIVE,
        revision_sequence: int = 0,
        availability: UtcTimestamp | None = None,
    ) -> None:
        if news_item_key not in self.items:
            self.items[news_item_key] = NewsItem(
                news_item_key=news_item_key,
                first_seen_at=first_seen_at,
                first_observation_mode=observation_mode,
            )
        vintage = NewsItemVintage(
            news_item_key=news_item_key,
            revision_sequence=revision_sequence,
            availability=availability or first_seen_at,
            observation_mode=observation_mode,
            headline=headline,
            source_channel="test_channel",
            observed_source_channels=("test_channel",),
            source_status=source_status,
            evidence_disposition=evidence_disposition,
            quarantine_reason=(
                "test fixture"
                if evidence_disposition is NewsEvidenceDisposition.QUARANTINED
                else None
            ),
        )
        self.vintages.setdefault(news_item_key, []).append(vintage)

    def add_relation(
        self,
        left: str,
        right: str,
        *,
        availability: UtcTimestamp,
        relation_kind: NewsCanonicalRelationKind = NewsCanonicalRelationKind.SAME_STORY,
        method: NewsCanonicalizationMethod = NewsCanonicalizationMethod.EXACT_CANONICAL_URL,
        revision_sequence: int = 0,
    ) -> None:
        left_key, right_key = sorted((left, right))
        self.relations.append(
            NewsCanonicalRelationVintage(
                left_news_item_key=left_key,
                right_news_item_key=right_key,
                revision_sequence=revision_sequence,
                availability=availability,
                relation_kind=relation_kind,
                method=method,
                left_item_revision_sequence=0,
                right_item_revision_sequence=0,
                algorithm_version="fx58_v2",
            )
        )

    def add_annotation(
        self,
        news_item_key: str,
        *,
        availability: UtcTimestamp,
        basis_news_item_revision_sequence: int = 0,
        classification: NewsSemanticClassification,
        algorithm_version: str = "fx59_v1",
        revision_sequence: int = 0,
    ) -> None:
        self.annotations.setdefault(news_item_key, []).append(
            NewsSemanticAnnotationVintage(
                news_item_key=news_item_key,
                revision_sequence=revision_sequence,
                availability=availability,
                basis_news_item_revision_sequence=basis_news_item_revision_sequence,
                algorithm_version=algorithm_version,
                classification=classification,
            )
        )


def classification(
    *,
    institution: str = "FEDERAL_RESERVE",
    jurisdiction: str = "UNITED_STATES",
    currency_relevance: tuple[NewsCurrencyRelevance, ...] = (),
    topics: tuple[NewsTopicAnnotation, ...] = (),
    extra_entities: tuple[NewsEntityAnnotation, ...] = (),
) -> NewsSemanticClassification:
    entities = (
        NewsEntityAnnotation(
            entity_type=NewsEntityType.INSTITUTION,
            entity_key=institution,
            evidence=(NewsEntityEvidenceKind.SOURCE_PROFILE,),
        ),
        NewsEntityAnnotation(
            entity_type=NewsEntityType.JURISDICTION,
            entity_key=jurisdiction,
            evidence=(NewsEntityEvidenceKind.SOURCE_PROFILE,),
        ),
        *extra_entities,
    )
    return NewsSemanticClassification(
        entities=tuple(sorted(entities, key=lambda e: (e.entity_type.value, e.entity_key))),
        topics=topics,
        currency_relevance=currency_relevance
        or (
            NewsCurrencyRelevance(
                currency_code="USD", reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,)
            ),
        ),
    )


class FakeNewsRepository:
    def __init__(self, world: FakeWorld) -> None:
        self._world = world

    async def register_source_item_with_first_vintage(self, *a: object, **k: object) -> object:
        raise NotImplementedError

    async def get_item(self, news_item_key: str) -> NewsItem | None:
        return self._world.items.get(news_item_key)

    async def get_item_by_source_identity(self, identity: NewsSourceIdentity) -> NewsItem | None:
        raise NotImplementedError

    async def add_vintage(self, vintage: NewsItemVintage) -> NewsVintageWriteOutcome:
        raise NotImplementedError

    async def list_vintages(self, news_item_key: str) -> tuple[NewsItemVintage, ...]:
        return tuple(self._world.vintages.get(news_item_key, []))

    async def latest_vintage_as_of(
        self, news_item_key: str, as_of: UtcTimestamp
    ) -> NewsItemVintage | None:
        raise NotImplementedError

    async def latest_evidence_eligible_vintage_as_of(
        self, news_item_key: str, as_of: UtcTimestamp, *, include_backfill: bool = False
    ) -> NewsItemVintage | None:
        candidates = [
            v
            for v in self._world.vintages.get(news_item_key, [])
            if v.availability.value <= as_of.value
            and v.evidence_disposition is NewsEvidenceDisposition.EVIDENCE_ELIGIBLE
            and (include_backfill or v.observation_mode is NewsObservationMode.PROSPECTIVE)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda v: (v.availability.value, v.revision_sequence))

    async def latest_evidence_eligible_vintages_as_of(
        self,
        news_item_keys: tuple[str, ...],
        as_of: UtcTimestamp,
        *,
        include_backfill: bool = False,
    ) -> dict[str, NewsItemVintage]:
        # Deliberately a NAIVE, obviously-correct implementation
        # calling the single-item method once per key -- this fake's
        # own job is only to prove `GetPairNewsEvidenceSnapshot`'s own
        # orchestration logic; batch-vs-single-item EQUIVALENCE for
        # the REAL SQL implementation is proven separately, against
        # real Postgres, in `tests/integration/test_news_repository_
        # batch_lookups.py`.
        result: dict[str, NewsItemVintage] = {}
        for key in news_item_keys:
            vintage = await self.latest_evidence_eligible_vintage_as_of(
                key, as_of, include_backfill=include_backfill
            )
            if vintage is not None:
                result[key] = vintage
        return result


class FakeNewsCanonicalizationRepository:
    def __init__(self, world: FakeWorld) -> None:
        self._world = world

    async def list_candidates_as_of(self, *a: object, **k: object) -> object:
        raise NotImplementedError

    async def list_items_seen_as_of(self, as_of: UtcTimestamp) -> tuple[NewsItem, ...]:
        return tuple(i for i in self._world.items.values() if i.first_seen_at.value <= as_of.value)

    async def latest_relation_for_pair(self, left: str, right: str) -> object:
        raise NotImplementedError

    async def latest_relation_as_of(self, left: str, right: str, as_of: UtcTimestamp) -> object:
        raise NotImplementedError

    async def list_relation_vintages_for_pair(self, left: str, right: str) -> object:
        raise NotImplementedError

    async def list_latest_relation_states_as_of(
        self, as_of: UtcTimestamp
    ) -> tuple[NewsCanonicalRelationVintage, ...]:
        qualifying = [r for r in self._world.relations if r.availability.value <= as_of.value]
        latest_by_pair: dict[tuple[str, str], NewsCanonicalRelationVintage] = {}
        for relation in qualifying:
            pair_key = (relation.left_news_item_key, relation.right_news_item_key)
            current = latest_by_pair.get(pair_key)
            sort_key = (relation.availability.value, relation.revision_sequence)
            if current is None or sort_key > (
                current.availability.value,
                current.revision_sequence,
            ):
                latest_by_pair[pair_key] = relation
        return tuple(latest_by_pair.values())

    async def add_relation_vintage(self, vintage: object) -> object:
        raise NotImplementedError


class FakeNewsSemanticRepository:
    def __init__(self, world: FakeWorld) -> None:
        self._world = world

    async def list_candidates_as_of(self, *a: object, **k: object) -> object:
        raise NotImplementedError

    async def latest_annotation_for_item(self, news_item_key: str) -> object:
        raise NotImplementedError

    async def latest_annotation_as_of(
        self, news_item_key: str, as_of: UtcTimestamp
    ) -> NewsSemanticAnnotationVintage | None:
        candidates = [
            a
            for a in self._world.annotations.get(news_item_key, [])
            if a.availability.value <= as_of.value
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda a: (a.availability.value, a.revision_sequence))

    async def latest_annotations_as_of(
        self, news_item_keys: tuple[str, ...], as_of: UtcTimestamp
    ) -> dict[str, NewsSemanticAnnotationVintage]:
        # Deliberately naive -- see `FakeNewsRepository.latest_
        # evidence_eligible_vintages_as_of`'s own comment.
        result: dict[str, NewsSemanticAnnotationVintage] = {}
        for key in news_item_keys:
            annotation = await self.latest_annotation_as_of(key, as_of)
            if annotation is not None:
                result[key] = annotation
        return result

    async def list_annotation_vintages_for_item(self, news_item_key: str) -> object:
        raise NotImplementedError

    async def list_latest_annotation_states_as_of(self, as_of: UtcTimestamp) -> object:
        raise NotImplementedError

    async def add_annotation_vintage(self, vintage: object) -> object:
        raise NotImplementedError


def _make_snapshot_getter(world: FakeWorld) -> GetPairNewsEvidenceSnapshot:
    return GetPairNewsEvidenceSnapshot(
        FakeNewsRepository(world),
        FakeNewsCanonicalizationRepository(world),  # type: ignore[arg-type]
        FakeNewsSemanticRepository(world),
    )


# --- Basic shape / policy version -------------------------------------------


@pytest.mark.asyncio
async def test_empty_snapshot_is_valid() -> None:
    world = FakeWorld()
    get_snapshot = _make_snapshot_getter(world)

    snapshot = await get_snapshot(EURUSD, _ts(0), _ts(23))

    assert snapshot.policy_version == SNAPSHOT_POLICY_VERSION
    assert snapshot.active_entries == ()
    assert snapshot.withdrawn_only_entries == ()
    assert snapshot.semantic_gaps == ()
    assert snapshot.coverage is NewsPairSemanticCoverage.COMPLETE


@pytest.mark.asyncio
async def test_window_start_after_as_of_rejected() -> None:
    world = FakeWorld()
    get_snapshot = _make_snapshot_getter(world)

    with pytest.raises(ValueError, match="window_start"):
        await get_snapshot(EURUSD, _ts(12), _ts(10))


# --- Section 57: canonical dedup --------------------------------------------


@pytest.mark.asyncio
async def test_canonical_dedup_one_group_one_entry() -> None:
    world = FakeWorld()
    world.add_item("A", first_seen_at=_ts(9))
    world.add_item("B", first_seen_at=_ts(9, 30))
    world.add_relation("A", "B", availability=_ts(10))
    world.add_annotation(
        "A",
        availability=_ts(9, 5),
        classification=classification(
            currency_relevance=(
                NewsCurrencyRelevance(
                    currency_code="EUR", reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,)
                ),
            )
        ),
    )
    world.add_annotation(
        "B",
        availability=_ts(9, 35),
        classification=classification(
            currency_relevance=(
                NewsCurrencyRelevance(
                    currency_code="USD", reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,)
                ),
            )
        ),
    )

    get_snapshot = _make_snapshot_getter(world)
    snapshot = await get_snapshot(EURUSD, _ts(0), _ts(10))

    assert len(snapshot.active_entries) == 1
    entry = snapshot.active_entries[0]
    assert set(entry.member_news_item_keys) == {"A", "B"}
    assert entry.pair_relevance_side is NewsPairRelevanceSide.BOTH


# --- Section 69: withdrawal lifecycle ---------------------------------------


@pytest.mark.asyncio
async def test_active_relevant_member_goes_to_active_entries() -> None:
    world = FakeWorld()
    world.add_item("A", first_seen_at=_ts(9), source_status=NewsSourceStatus.ACTIVE)
    world.add_annotation("A", availability=_ts(9, 5), classification=classification())

    get_snapshot = _make_snapshot_getter(world)
    snapshot = await get_snapshot(EURUSD, _ts(0), _ts(10))

    assert len(snapshot.active_entries) == 1
    assert snapshot.withdrawn_only_entries == ()


@pytest.mark.asyncio
async def test_withdrawn_relevant_member_goes_to_withdrawn_only_entries() -> None:
    world = FakeWorld()
    world.add_item("A", first_seen_at=_ts(9), source_status=NewsSourceStatus.WITHDRAWN)
    world.add_annotation("A", availability=_ts(9, 5), classification=classification())

    get_snapshot = _make_snapshot_getter(world)
    snapshot = await get_snapshot(EURUSD, _ts(0), _ts(10))

    assert snapshot.active_entries == ()
    assert len(snapshot.withdrawn_only_entries) == 1
    group = snapshot.withdrawn_only_entries[0]
    assert group.withdrawn_relevant_member_keys == ("A",)
    assert group.active_relevant_member_keys == ()


@pytest.mark.asyncio
async def test_mixed_active_and_withdrawn_is_active_with_both_preserved() -> None:
    world = FakeWorld()
    world.add_item("A", first_seen_at=_ts(9), source_status=NewsSourceStatus.ACTIVE)
    world.add_item("B", first_seen_at=_ts(9, 10), source_status=NewsSourceStatus.WITHDRAWN)
    world.add_relation("A", "B", availability=_ts(9, 20))
    world.add_annotation("A", availability=_ts(9, 5), classification=classification())
    world.add_annotation("B", availability=_ts(9, 15), classification=classification())

    get_snapshot = _make_snapshot_getter(world)
    snapshot = await get_snapshot(EURUSD, _ts(0), _ts(10))

    assert len(snapshot.active_entries) == 1
    group = snapshot.active_entries[0]
    assert group.active_relevant_member_keys == ("A",)
    assert group.withdrawn_relevant_member_keys == ("B",)


# --- Section 70: display member ---------------------------------------------


@pytest.mark.asyncio
async def test_display_member_is_earliest_active() -> None:
    world = FakeWorld()
    world.add_item("B", first_seen_at=_ts(10), source_status=NewsSourceStatus.ACTIVE)
    world.add_item("A", first_seen_at=_ts(9), source_status=NewsSourceStatus.ACTIVE)
    world.add_relation("A", "B", availability=_ts(10, 30))
    world.add_annotation("A", availability=_ts(9, 5), classification=classification())
    world.add_annotation("B", availability=_ts(10, 5), classification=classification())

    get_snapshot = _make_snapshot_getter(world)
    snapshot = await get_snapshot(EURUSD, _ts(0), _ts(11))

    assert snapshot.active_entries[0].display_member_news_item_key == "A"


@pytest.mark.asyncio
async def test_display_member_prefers_active_over_withdrawn() -> None:
    world = FakeWorld()
    world.add_item("A", first_seen_at=_ts(9), source_status=NewsSourceStatus.WITHDRAWN)
    world.add_item("B", first_seen_at=_ts(10), source_status=NewsSourceStatus.ACTIVE)
    world.add_relation("A", "B", availability=_ts(10, 30))
    world.add_annotation("A", availability=_ts(9, 5), classification=classification())
    world.add_annotation("B", availability=_ts(10, 5), classification=classification())

    get_snapshot = _make_snapshot_getter(world)
    snapshot = await get_snapshot(EURUSD, _ts(0), _ts(11))

    # A is earlier but withdrawn; B is active -- B must be the display member.
    assert snapshot.active_entries[0].display_member_news_item_key == "B"


# --- Section 71/72: topic/entity union --------------------------------------


@pytest.mark.asyncio
async def test_topic_union_across_members() -> None:
    world = FakeWorld()
    world.add_item("A", first_seen_at=_ts(9))
    world.add_item("B", first_seen_at=_ts(9, 10))
    world.add_relation("A", "B", availability=_ts(9, 20))
    world.add_annotation(
        "A",
        availability=_ts(9, 5),
        classification=classification(
            topics=(NewsTopicAnnotation(topic=NewsTopic.MONETARY_POLICY, matched_terms=("x",)),)
        ),
    )
    world.add_annotation(
        "B",
        availability=_ts(9, 15),
        classification=classification(
            topics=(
                NewsTopicAnnotation(topic=NewsTopic.INFLATION_PRICES, matched_terms=("y",)),
                NewsTopicAnnotation(topic=NewsTopic.MONETARY_POLICY, matched_terms=("x",)),
            )
        ),
    )

    get_snapshot = _make_snapshot_getter(world)
    snapshot = await get_snapshot(EURUSD, _ts(0), _ts(10))

    assert snapshot.active_entries[0].topics == (
        NewsTopic.INFLATION_PRICES,
        NewsTopic.MONETARY_POLICY,
    )


@pytest.mark.asyncio
async def test_entity_union_across_members() -> None:
    world = FakeWorld()
    world.add_item("A", first_seen_at=_ts(9))
    world.add_item("B", first_seen_at=_ts(9, 10))
    world.add_relation("A", "B", availability=_ts(9, 20))
    world.add_annotation(
        "A", availability=_ts(9, 5), classification=classification(institution="FEDERAL_RESERVE")
    )
    world.add_annotation(
        "B",
        availability=_ts(9, 15),
        classification=classification(
            institution="EUROPEAN_CENTRAL_BANK", jurisdiction="EURO_AREA"
        ),
    )

    get_snapshot = _make_snapshot_getter(world)
    snapshot = await get_snapshot(EURUSD, _ts(0), _ts(10))

    entity_keys = {e.entity_key for e in snapshot.active_entries[0].entities}
    assert "FEDERAL_RESERVE" in entity_keys
    assert "EUROPEAN_CENTRAL_BANK" in entity_keys


# --- Section 67: stale member in an otherwise-irrelevant group -------------


@pytest.mark.asyncio
async def test_stale_member_in_irrelevant_group_surfaces_as_gap_not_hidden() -> None:
    world = FakeWorld()
    world.add_item("A", first_seen_at=_ts(9))
    world.add_item("B", first_seen_at=_ts(9, 10))
    world.add_relation("A", "B", availability=_ts(9, 20))
    # A: CURRENT, CAD-only (irrelevant to EUR/USD).
    world.add_annotation(
        "A",
        availability=_ts(9, 5),
        classification=classification(
            currency_relevance=(
                NewsCurrencyRelevance(
                    currency_code="CAD", reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,)
                ),
            )
        ),
    )
    # B: no annotation at all -> UNCLASSIFIED.

    get_snapshot = _make_snapshot_getter(world)
    snapshot = await get_snapshot(EURUSD, _ts(0), _ts(10))

    assert snapshot.active_entries == ()
    assert snapshot.withdrawn_only_entries == ()
    assert snapshot.coverage is NewsPairSemanticCoverage.INCOMPLETE_SEMANTICS
    assert len(snapshot.semantic_gaps) == 1
    assert snapshot.semantic_gaps[0].news_item_key == "B"


@pytest.mark.asyncio
async def test_group_with_no_gaps_and_no_relevance_counts_as_pair_irrelevant() -> None:
    world = FakeWorld()
    world.add_item("A", first_seen_at=_ts(9))
    world.add_annotation(
        "A",
        availability=_ts(9, 5),
        classification=classification(
            currency_relevance=(
                NewsCurrencyRelevance(
                    currency_code="CAD", reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,)
                ),
            )
        ),
    )

    get_snapshot = _make_snapshot_getter(world)
    snapshot = await get_snapshot(EURUSD, _ts(0), _ts(10))

    assert snapshot.coverage is NewsPairSemanticCoverage.COMPLETE
    assert snapshot.groups_pair_irrelevant == 1
    assert snapshot.semantic_gaps == ()


# --- FX-60H H1: complete snapshot accounting --------------------------------


@pytest.mark.asyncio
async def test_accounting_singleton_pair_relevant_group() -> None:
    world = FakeWorld()
    world.add_item("A", first_seen_at=_ts(9))
    world.add_annotation("A", availability=_ts(9, 5), classification=classification())

    get_snapshot = _make_snapshot_getter(world)
    snapshot = await get_snapshot(EURUSD, _ts(0), _ts(10))

    acc = snapshot.accounting
    assert acc.items_pit_visible == 1
    assert acc.items_snapshot_eligible == 1
    assert acc.items_window_eligible == 1
    assert acc.items_current == 1
    assert acc.items_stale == 0
    assert acc.items_unclassified == 0
    assert acc.items_pair_relevant == 1
    assert acc.groups_total == 1
    assert acc.groups_outside_window == 0
    assert acc.groups_without_eligible_evidence == 0
    assert acc.groups_pair_irrelevant == 0
    assert acc.groups_incomplete_semantics == 0
    # Default `classification()` carries USD-only relevance -- for
    # EUR/USD that is QUOTE_ONLY, not BOTH.
    assert acc.groups_quote_only == 1
    assert acc.groups_base_only == 0
    assert acc.groups_both == 0


@pytest.mark.asyncio
async def test_accounting_duplicate_group_counts_two_items_one_group() -> None:
    world = FakeWorld()
    world.add_item("A", first_seen_at=_ts(9))
    world.add_item("B", first_seen_at=_ts(9, 30))
    world.add_relation("A", "B", availability=_ts(10))
    world.add_annotation(
        "A",
        availability=_ts(9, 5),
        classification=classification(
            currency_relevance=(
                NewsCurrencyRelevance(
                    currency_code="EUR", reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,)
                ),
            )
        ),
    )
    world.add_annotation(
        "B",
        availability=_ts(9, 35),
        classification=classification(
            currency_relevance=(
                NewsCurrencyRelevance(
                    currency_code="USD", reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,)
                ),
            )
        ),
    )

    get_snapshot = _make_snapshot_getter(world)
    snapshot = await get_snapshot(EURUSD, _ts(0), _ts(10))

    acc = snapshot.accounting
    assert acc.items_pit_visible == 2
    assert acc.items_window_eligible == 2
    assert acc.items_current == 2
    assert acc.items_pair_relevant == 2
    assert acc.groups_total == 1
    assert acc.groups_both == 1


@pytest.mark.asyncio
async def test_accounting_mixed_active_withdrawn_group_counts_one_group() -> None:
    world = FakeWorld()
    world.add_item("A", first_seen_at=_ts(9), source_status=NewsSourceStatus.ACTIVE)
    world.add_item("B", first_seen_at=_ts(9, 10), source_status=NewsSourceStatus.WITHDRAWN)
    world.add_relation("A", "B", availability=_ts(9, 20))
    world.add_annotation("A", availability=_ts(9, 5), classification=classification())
    world.add_annotation("B", availability=_ts(9, 15), classification=classification())

    get_snapshot = _make_snapshot_getter(world)
    snapshot = await get_snapshot(EURUSD, _ts(0), _ts(10))

    acc = snapshot.accounting
    assert acc.items_window_eligible == 2
    assert acc.items_current == 2
    assert acc.items_pair_relevant == 2
    assert acc.groups_total == 1
    # Both members use default `classification()` (USD-only relevance)
    # -- for EUR/USD that is QUOTE_ONLY, not BOTH.
    assert acc.groups_quote_only == 1
    assert acc.groups_both == 0
    assert acc.groups_outside_window == 0


@pytest.mark.asyncio
async def test_accounting_out_of_window_group_not_counted_in_item_or_relevance_buckets() -> None:
    world = FakeWorld()
    world.add_item("A", first_seen_at=_ts(1))
    world.add_annotation("A", availability=_ts(1, 5), classification=classification())

    get_snapshot = _make_snapshot_getter(world)
    # window_start is AFTER A's own first_seen_at -- A's group falls outside the window.
    snapshot = await get_snapshot(EURUSD, _ts(5), _ts(10))

    acc = snapshot.accounting
    assert acc.items_pit_visible == 1
    assert acc.items_snapshot_eligible == 1
    assert acc.items_window_eligible == 0
    assert acc.items_current == 0
    assert acc.items_stale == 0
    assert acc.items_unclassified == 0
    assert acc.items_pair_relevant == 0
    assert acc.groups_total == 1
    assert acc.groups_outside_window == 1
    assert acc.groups_without_eligible_evidence == 0
    assert acc.groups_pair_irrelevant == 0
    assert acc.groups_incomplete_semantics == 0
    assert snapshot.active_entries == ()
    assert snapshot.withdrawn_only_entries == ()


@pytest.mark.asyncio
async def test_accounting_group_without_eligible_evidence_not_counted_elsewhere() -> None:
    world = FakeWorld()
    # Quarantined -- never evidence-eligible, so this group has zero
    # eligible members at all.
    world.add_item(
        "A", first_seen_at=_ts(9), evidence_disposition=NewsEvidenceDisposition.QUARANTINED
    )

    get_snapshot = _make_snapshot_getter(world)
    snapshot = await get_snapshot(EURUSD, _ts(0), _ts(10))

    acc = snapshot.accounting
    assert acc.items_pit_visible == 1
    assert acc.items_snapshot_eligible == 0
    assert acc.items_window_eligible == 0
    assert acc.groups_total == 1
    assert acc.groups_without_eligible_evidence == 1
    assert acc.groups_outside_window == 0
    assert acc.groups_pair_irrelevant == 0
    assert acc.groups_incomplete_semantics == 0


@pytest.mark.asyncio
async def test_accounting_semantically_incomplete_group_not_counted_as_pair_irrelevant() -> None:
    """The real FX-60 accounting gap this hardening pass closes: a
    group with a semantic gap and NO confirmed-relevant member must
    land in `groups_incomplete_semantics`, never `groups_pair_
    irrelevant` -- relevance here is genuinely UNRESOLVED, not
    confirmed absent."""
    world = FakeWorld()
    world.add_item("A", first_seen_at=_ts(9))
    world.add_item("B", first_seen_at=_ts(9, 10))
    world.add_relation("A", "B", availability=_ts(9, 20))
    # A: CURRENT, CAD-only (irrelevant to EUR/USD).
    world.add_annotation(
        "A",
        availability=_ts(9, 5),
        classification=classification(
            currency_relevance=(
                NewsCurrencyRelevance(
                    currency_code="CAD", reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,)
                ),
            )
        ),
    )
    # B: no annotation at all -> UNCLASSIFIED (unresolved).

    get_snapshot = _make_snapshot_getter(world)
    snapshot = await get_snapshot(EURUSD, _ts(0), _ts(10))

    acc = snapshot.accounting
    assert acc.items_window_eligible == 2
    assert acc.items_current == 1
    assert acc.items_unclassified == 1
    assert acc.items_pair_relevant == 0
    assert acc.groups_total == 1
    assert acc.groups_incomplete_semantics == 1
    assert acc.groups_pair_irrelevant == 0
    assert acc.groups_base_only == acc.groups_quote_only == acc.groups_both == 0


@pytest.mark.asyncio
async def test_accounting_fully_resolved_irrelevant_group_counts_separately_from_incomplete() -> (
    None
):
    world = FakeWorld()
    world.add_item("A", first_seen_at=_ts(9))
    world.add_annotation(
        "A",
        availability=_ts(9, 5),
        classification=classification(
            currency_relevance=(
                NewsCurrencyRelevance(
                    currency_code="CAD", reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,)
                ),
            )
        ),
    )

    get_snapshot = _make_snapshot_getter(world)
    snapshot = await get_snapshot(EURUSD, _ts(0), _ts(10))

    acc = snapshot.accounting
    assert acc.items_current == 1
    assert acc.items_pair_relevant == 0
    assert acc.groups_pair_irrelevant == 1
    assert acc.groups_incomplete_semantics == 0


@pytest.mark.asyncio
async def test_accounting_reconciles_across_many_mixed_groups() -> None:
    """A single snapshot combining every group disposition at once --
    singleton, duplicate, mixed active/withdrawn, out-of-window,
    without-eligible-evidence, pair-irrelevant, and incomplete-
    semantics -- still reconciles exactly; `NewsPairSnapshotAccounting.
    __post_init__` would already fail closed on any arithmetic drift,
    so a successful construction plus these explicit per-bucket
    assertions together prove the invariant end-to-end."""
    world = FakeWorld()

    # Group 1: singleton, pair-relevant (BOTH side via two annotations
    # is not needed -- use base+quote on one member for BOTH).
    world.add_item("G1", first_seen_at=_ts(9))
    world.add_annotation(
        "G1",
        availability=_ts(9, 1),
        classification=classification(
            currency_relevance=(
                NewsCurrencyRelevance(
                    currency_code="EUR", reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,)
                ),
                NewsCurrencyRelevance(
                    currency_code="USD", reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,)
                ),
            )
        ),
    )

    # Group 2: duplicate (two members), quote-only.
    world.add_item("G2A", first_seen_at=_ts(9, 10))
    world.add_item("G2B", first_seen_at=_ts(9, 15))
    world.add_relation("G2A", "G2B", availability=_ts(9, 20))
    for key, ts in (("G2A", _ts(9, 11)), ("G2B", _ts(9, 16))):
        world.add_annotation(
            key,
            availability=ts,
            classification=classification(
                currency_relevance=(
                    NewsCurrencyRelevance(
                        currency_code="USD",
                        reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,),
                    ),
                )
            ),
        )

    # Group 3: out-of-window (first_seen_at before window_start).
    world.add_item("G3", first_seen_at=_ts(1))
    world.add_annotation("G3", availability=_ts(1, 1), classification=classification())

    # Group 4: no eligible evidence (quarantined).
    world.add_item(
        "G4", first_seen_at=_ts(9, 25), evidence_disposition=NewsEvidenceDisposition.QUARANTINED
    )

    # Group 5: fully resolved, confirmed pair-irrelevant.
    world.add_item("G5", first_seen_at=_ts(9, 30))
    world.add_annotation(
        "G5",
        availability=_ts(9, 31),
        classification=classification(
            currency_relevance=(
                NewsCurrencyRelevance(
                    currency_code="CAD", reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,)
                ),
            )
        ),
    )

    # Group 6: semantically incomplete (gap, no confirmed relevance).
    world.add_item("G6", first_seen_at=_ts(9, 40))
    # No annotation at all -> UNCLASSIFIED.

    get_snapshot = _make_snapshot_getter(world)
    snapshot = await get_snapshot(EURUSD, _ts(5), _ts(10))

    acc = snapshot.accounting
    assert acc.groups_total == 6
    assert acc.groups_outside_window == 1  # G3
    assert acc.groups_without_eligible_evidence == 1  # G4
    assert acc.groups_pair_irrelevant == 1  # G5
    assert acc.groups_incomplete_semantics == 1  # G6
    assert acc.groups_both == 1  # G1
    assert acc.groups_quote_only == 1  # G2
    assert acc.groups_base_only == 0
    assert isinstance(snapshot.accounting, NewsPairSnapshotAccounting)


def test_accounting_rejects_group_disposition_sum_mismatch() -> None:
    with pytest.raises(ValueError, match="mutually exclusive group dispositions"):
        NewsPairSnapshotAccounting(
            items_pit_visible=1,
            items_snapshot_eligible=1,
            items_window_eligible=1,
            items_current=1,
            items_stale=0,
            items_unclassified=0,
            items_pair_relevant=0,
            groups_total=2,
            groups_outside_window=0,
            groups_without_eligible_evidence=0,
            groups_pair_irrelevant=0,
            groups_incomplete_semantics=0,
            groups_base_only=0,
            groups_quote_only=0,
            groups_both=0,
        )


def test_accounting_rejects_item_semantic_breakdown_mismatch() -> None:
    with pytest.raises(ValueError, match="must equal items_window_eligible"):
        NewsPairSnapshotAccounting(
            items_pit_visible=1,
            items_snapshot_eligible=1,
            items_window_eligible=1,
            items_current=0,
            items_stale=0,
            items_unclassified=0,
            items_pair_relevant=0,
            groups_total=0,
            groups_outside_window=0,
            groups_without_eligible_evidence=0,
            groups_pair_irrelevant=0,
            groups_incomplete_semantics=0,
            groups_base_only=0,
            groups_quote_only=0,
            groups_both=0,
        )


# --- FX-60H H2: canonical relation provenance --------------------------------


@pytest.mark.asyncio
async def test_relation_provenance_empty_for_singleton_group() -> None:
    world = FakeWorld()
    world.add_item("A", first_seen_at=_ts(9))
    world.add_annotation("A", availability=_ts(9, 5), classification=classification())

    get_snapshot = _make_snapshot_getter(world)
    snapshot = await get_snapshot(EURUSD, _ts(0), _ts(10))

    assert snapshot.active_entries[0].relation_provenance == ()


@pytest.mark.asyncio
async def test_relation_provenance_lists_the_direct_edge_for_a_pair() -> None:
    world = FakeWorld()
    world.add_item("A", first_seen_at=_ts(9))
    world.add_item("B", first_seen_at=_ts(9, 10))
    world.add_relation("A", "B", availability=_ts(9, 20))
    world.add_annotation("A", availability=_ts(9, 5), classification=classification())
    world.add_annotation("B", availability=_ts(9, 15), classification=classification())

    get_snapshot = _make_snapshot_getter(world)
    snapshot = await get_snapshot(EURUSD, _ts(0), _ts(10))

    provenance = snapshot.active_entries[0].relation_provenance
    assert len(provenance) == 1
    assert (provenance[0].left_news_item_key, provenance[0].right_news_item_key) == ("A", "B")


@pytest.mark.asyncio
async def test_relation_provenance_lists_real_transitive_edges_not_a_phantom_edge() -> None:
    """A-SAME-B, B-SAME-C, NO direct A-C edge -- all three canonicalize
    into one group, but provenance must list exactly the two REAL
    edges, never a synthesized A-C edge."""
    world = FakeWorld()
    world.add_item("A", first_seen_at=_ts(9))
    world.add_item("B", first_seen_at=_ts(9, 10))
    world.add_item("C", first_seen_at=_ts(9, 20))
    world.add_relation("A", "B", availability=_ts(9, 30))
    world.add_relation("B", "C", availability=_ts(9, 40))
    for key, ts in (("A", _ts(9, 5)), ("B", _ts(9, 15)), ("C", _ts(9, 25))):
        world.add_annotation(key, availability=ts, classification=classification())

    get_snapshot = _make_snapshot_getter(world)
    snapshot = await get_snapshot(EURUSD, _ts(0), _ts(10))

    assert set(snapshot.active_entries[0].member_news_item_keys) == {"A", "B", "C"}
    provenance_pairs = {
        (r.left_news_item_key, r.right_news_item_key)
        for r in snapshot.active_entries[0].relation_provenance
    }
    assert provenance_pairs == {("A", "B"), ("B", "C")}
    assert ("A", "C") not in provenance_pairs


@pytest.mark.asyncio
async def test_relation_provenance_pit_filtered_relation_after_as_of_excluded() -> None:
    """A relation whose own `availability` is AFTER the requested
    `as_of` must not appear in an earlier snapshot's own provenance --
    the group still canonicalizes as two singletons at the earlier
    instant, since `list_latest_relation_states_as_of` itself is
    PIT-filtered (Section 8), and provenance reuses that same call."""
    world = FakeWorld()
    world.add_item("A", first_seen_at=_ts(9))
    world.add_item("B", first_seen_at=_ts(9, 10))
    world.add_relation("A", "B", availability=_ts(9, 50))
    world.add_annotation("A", availability=_ts(9, 5), classification=classification())
    world.add_annotation("B", availability=_ts(9, 15), classification=classification())

    get_snapshot = _make_snapshot_getter(world)

    earlier_snapshot = await get_snapshot(EURUSD, _ts(0), _ts(9, 20))
    assert len(earlier_snapshot.active_entries) == 2
    for entry in earlier_snapshot.active_entries:
        assert entry.relation_provenance == ()

    later_snapshot = await get_snapshot(EURUSD, _ts(0), _ts(10))
    assert len(later_snapshot.active_entries) == 1
    assert len(later_snapshot.active_entries[0].relation_provenance) == 1


# --- FX-60H.1: canonical membership vs evidence eligibility ------------------


@pytest.mark.asyncio
async def test_h2_1_ineligible_intermediate_member_retains_connecting_relations() -> None:
    """Mandatory example (FX-60H.1 Section 1): A-SAME-B-SAME-C, with B
    QUARANTINED (PIT-visible, but never evidence-eligible). FX-58
    still derives ONE canonical group of all three; FX-60 correctly
    lets only A and C contribute evidence; `relation_provenance` must
    still retain BOTH the A-B and B-C edges, since they are what
    establishes A and C's own canonical connection -- the bug this
    story corrects dropped both edges because B wasn't eligible."""
    world = FakeWorld()
    world.add_item("A", first_seen_at=_ts(9))
    world.add_item(
        "B", first_seen_at=_ts(9, 5), evidence_disposition=NewsEvidenceDisposition.QUARANTINED
    )
    world.add_item("C", first_seen_at=_ts(9, 10))
    world.add_relation("A", "B", availability=_ts(9, 20))
    world.add_relation("B", "C", availability=_ts(9, 25))
    world.add_annotation("A", availability=_ts(9, 1), classification=classification())
    world.add_annotation("C", availability=_ts(9, 11), classification=classification())
    # B has NO annotation either -- it contributes nothing, period.

    get_snapshot = _make_snapshot_getter(world)
    snapshot = await get_snapshot(EURUSD, _ts(0), _ts(10))

    assert snapshot.accounting.groups_total == 1  # one canonical group, not 3
    assert len(snapshot.active_entries) == 1
    entry = snapshot.active_entries[0]

    # Evidence eligibility: B is excluded entirely.
    assert entry.member_news_item_keys == ("A", "C")
    assert {m.news_item_key for m in entry.members} == {"A", "C"}
    assert "B" not in entry.semantic_gap_member_keys
    assert "B" not in entry.active_relevant_member_keys
    assert "B" not in entry.withdrawn_relevant_member_keys

    # Canonical membership: B is present.
    assert entry.canonical_member_news_item_keys == ("A", "B", "C")

    # Both connecting edges survive, even though B itself is ineligible.
    provenance_pairs = {
        (r.left_news_item_key, r.right_news_item_key) for r in entry.relation_provenance
    }
    assert provenance_pairs == {("A", "B"), ("B", "C")}


@pytest.mark.asyncio
async def test_h2_2_stale_intermediate_member_retains_connecting_relations() -> None:
    """A PIT-visible, evidence-ELIGIBLE intermediate member (B) whose
    semantics are STALE (not UNCLASSIFIED/ineligible) -- the
    connecting relations must remain in provenance, and B's own
    existing semantic-gap behavior (surfaced, not hidden, not treated
    as confirmed-irrelevant) must be unchanged."""
    world = FakeWorld()
    world.add_item("A", first_seen_at=_ts(9))
    world.add_item("B", first_seen_at=_ts(9, 5), revision_sequence=0, availability=_ts(9, 5))
    # A second, later vintage revision for B -- its stored annotation
    # (basis_news_item_revision_sequence=0) no longer matches B's own
    # latest eligible vintage revision (1), so B resolves to STALE.
    world.add_item("B", first_seen_at=_ts(9, 5), revision_sequence=1, availability=_ts(9, 16))
    world.add_item("C", first_seen_at=_ts(9, 10))
    world.add_relation("A", "B", availability=_ts(9, 20))
    world.add_relation("B", "C", availability=_ts(9, 25))
    world.add_annotation("A", availability=_ts(9, 1), classification=classification())
    world.add_annotation(
        "B",
        availability=_ts(9, 6),
        basis_news_item_revision_sequence=0,
        classification=classification(),
    )
    world.add_annotation("C", availability=_ts(9, 11), classification=classification())

    get_snapshot = _make_snapshot_getter(world)
    snapshot = await get_snapshot(EURUSD, _ts(0), _ts(10))

    assert snapshot.accounting.groups_total == 1
    assert len(snapshot.active_entries) == 1
    entry = snapshot.active_entries[0]

    # B is evidence-ELIGIBLE (unlike H2-1) but STALE -- it surfaces as
    # a semantic gap, never silently hidden, never confirmed-irrelevant.
    assert "B" in entry.semantic_gap_member_keys
    assert len(snapshot.semantic_gaps) == 1
    assert snapshot.semantic_gaps[0].news_item_key == "B"
    assert snapshot.semantic_gaps[0].semantic_state is NewsSemanticState.STALE

    # The connecting relations remain, regardless of B's semantic state.
    provenance_pairs = {
        (r.left_news_item_key, r.right_news_item_key) for r in entry.relation_provenance
    }
    assert provenance_pairs == {("A", "B"), ("B", "C")}
    assert entry.canonical_member_news_item_keys == ("A", "B", "C")


@pytest.mark.asyncio
async def test_h2_3_future_relationship_pit_filtered_with_ineligible_connector() -> None:
    """A-SAME-B exists early; B-SAME-C is added only LATER (after the
    requested `as_of`), and B is ineligible throughout. At the
    earlier `as_of`, the canonical group is {A, B} only -- C is its
    own singleton. Provenance for {A, B} contains only the A-B edge.
    After the B-C relation becomes visible, the group grows to
    {A, B, C} with both edges. Reconstructing the EARLIER snapshot
    again, after the future relation has been added to storage, must
    produce the exact SAME earlier result -- proving the fix is
    genuinely PIT-safe, not merely "correct at the latest instant."""
    world = FakeWorld()
    world.add_item("A", first_seen_at=_ts(9))
    world.add_item(
        "B", first_seen_at=_ts(9, 5), evidence_disposition=NewsEvidenceDisposition.QUARANTINED
    )
    world.add_item("C", first_seen_at=_ts(9, 10))
    world.add_relation("A", "B", availability=_ts(9, 20))
    world.add_annotation("A", availability=_ts(9, 1), classification=classification())
    world.add_annotation("C", availability=_ts(9, 11), classification=classification())

    get_snapshot = _make_snapshot_getter(world)

    earlier_first = await get_snapshot(EURUSD, _ts(0), _ts(9, 30))
    assert earlier_first.accounting.groups_total == 2  # {A,B} and {C}
    a_entry_first = next(
        e for e in earlier_first.active_entries if "A" in e.canonical_member_news_item_keys
    )
    assert a_entry_first.canonical_member_news_item_keys == ("A", "B")
    assert a_entry_first.member_news_item_keys == ("A",)
    assert {
        (r.left_news_item_key, r.right_news_item_key) for r in a_entry_first.relation_provenance
    } == {("A", "B")}

    # The future relationship, added AFTER the earlier as_of above.
    world.add_relation("B", "C", availability=_ts(9, 40))

    # Reconstructing the SAME earlier as_of must be unchanged.
    earlier_second = await get_snapshot(EURUSD, _ts(0), _ts(9, 30))
    assert earlier_second.accounting.groups_total == 2
    a_entry_second = next(
        e for e in earlier_second.active_entries if "A" in e.canonical_member_news_item_keys
    )
    assert a_entry_second.canonical_member_news_item_keys == ("A", "B")
    assert {
        (r.left_news_item_key, r.right_news_item_key) for r in a_entry_second.relation_provenance
    } == {("A", "B")}

    # A later as_of now includes the future relation and all 3 members.
    later = await get_snapshot(EURUSD, _ts(0), _ts(10))
    assert later.accounting.groups_total == 1
    later_entry = later.active_entries[0]
    assert later_entry.canonical_member_news_item_keys == ("A", "B", "C")
    assert {
        (r.left_news_item_key, r.right_news_item_key) for r in later_entry.relation_provenance
    } == {("A", "B"), ("B", "C")}


@pytest.mark.asyncio
async def test_h2_4_multiple_connecting_paths_deterministic_no_duplicates() -> None:
    """A fully-connected triangle (A-B, B-C, A-C all SAME_STORY) --
    multiple redundant paths connect the same three members.
    Provenance must list all three real edges exactly once each, in
    canonical sorted order, with no duplicates."""
    world = FakeWorld()
    world.add_item("A", first_seen_at=_ts(9))
    world.add_item("B", first_seen_at=_ts(9, 5))
    world.add_item("C", first_seen_at=_ts(9, 10))
    world.add_relation("A", "B", availability=_ts(9, 20))
    world.add_relation("B", "C", availability=_ts(9, 25))
    world.add_relation("A", "C", availability=_ts(9, 30))
    for key, ts in (("A", _ts(9, 1)), ("B", _ts(9, 6)), ("C", _ts(9, 11))):
        world.add_annotation(key, availability=ts, classification=classification())

    get_snapshot = _make_snapshot_getter(world)
    snapshot = await get_snapshot(EURUSD, _ts(0), _ts(10))

    assert len(snapshot.active_entries) == 1
    provenance = snapshot.active_entries[0].relation_provenance
    provenance_pairs = [(r.left_news_item_key, r.right_news_item_key) for r in provenance]
    assert len(provenance_pairs) == len(set(provenance_pairs))  # no duplicates
    assert set(provenance_pairs) == {("A", "B"), ("A", "C"), ("B", "C")}
    assert provenance_pairs == sorted(provenance_pairs)  # canonical sorted order


@pytest.mark.asyncio
async def test_h2_5_ineligible_connector_does_not_affect_accounting() -> None:
    """An ineligible intermediate member must not change any item-
    level count, pair-relevant count, relevance category, topic/
    entity aggregation, or window anchor -- it only ever establishes
    canonical connectivity, never evidence."""
    world = FakeWorld()
    world.add_item("A", first_seen_at=_ts(9, 30))
    world.add_item(
        "B", first_seen_at=_ts(9, 5), evidence_disposition=NewsEvidenceDisposition.QUARANTINED
    )
    world.add_item("C", first_seen_at=_ts(9, 10))
    world.add_relation("A", "B", availability=_ts(9, 40))
    world.add_relation("B", "C", availability=_ts(9, 45))
    usd_relevance = (
        NewsCurrencyRelevance(
            currency_code="USD", reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,)
        ),
    )
    world.add_annotation(
        "A",
        availability=_ts(9, 31),
        classification=classification(currency_relevance=usd_relevance),
    )
    world.add_annotation(
        "C",
        availability=_ts(9, 11),
        classification=classification(currency_relevance=usd_relevance),
    )

    get_snapshot = _make_snapshot_getter(world)
    snapshot = await get_snapshot(EURUSD, _ts(0), _ts(10))

    acc = snapshot.accounting
    assert acc.items_pit_visible == 3
    assert acc.items_snapshot_eligible == 2  # A and C only, never B
    assert acc.items_window_eligible == 2
    assert acc.items_current == 2
    assert acc.items_stale == 0
    assert acc.items_unclassified == 0
    assert acc.items_pair_relevant == 2
    assert acc.groups_total == 1
    assert acc.groups_quote_only == 1  # USD-only relevance, quote side
    assert acc.groups_base_only == acc.groups_both == 0

    entry = snapshot.active_entries[0]
    # story_first_seen_at is the MIN first_seen_at among ELIGIBLE
    # members only (Section 13) -- B's earlier first_seen_at (9:05)
    # must NOT anchor the window even though B is a canonical member.
    assert entry.story_first_seen_at == _ts(
        9, 10
    )  # C's own first_seen_at, the earliest ELIGIBLE one
    assert entry.topics == ()
    assert len(entry.entities) == 2  # institution + jurisdiction, unioned from A and C only


def test_group_rejects_relation_provenance_edge_outside_membership() -> None:
    relation = NewsCanonicalRelationVintage(
        left_news_item_key="A",
        right_news_item_key="Z",
        revision_sequence=0,
        availability=_ts(9),
        relation_kind=NewsCanonicalRelationKind.SAME_STORY,
        method=NewsCanonicalizationMethod.EXACT_CANONICAL_URL,
        left_item_revision_sequence=0,
        right_item_revision_sequence=0,
        algorithm_version="fx58_v2",
    )
    member = NewsPairEvidenceMember(
        news_item_key="A",
        first_seen_at=_ts(9),
        basis_news_item_revision_sequence=0,
        news_vintage_availability=_ts(9),
        semantic_annotation_revision_sequence=0,
        semantic_annotation_availability=_ts(9),
        semantic_algorithm_version="fx59_v1",
        headline="H",
        summary=None,
        canonical_url=None,
        source_content_type=None,
        source_channel="test_channel",
        source_published_at=None,
        source_status=NewsSourceStatus.ACTIVE,
        classification=classification(),
        publisher_institution_entity_key="FEDERAL_RESERVE",
        publisher_jurisdiction_entity_key="UNITED_STATES",
    )
    with pytest.raises(ValueError, match="relation_provenance edges must connect"):
        NewsPairEvidenceGroup(
            canonical_group_key="A",
            story_first_seen_at=_ts(9),
            display_member_news_item_key="A",
            member_news_item_keys=("A",),
            canonical_member_news_item_keys=("A",),
            pair_relevance_side=NewsPairRelevanceSide.BOTH,
            base_relevance_reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,),
            quote_relevance_reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,),
            topics=(),
            entities=(),
            active_relevant_member_keys=("A",),
            withdrawn_relevant_member_keys=(),
            semantic_gap_member_keys=(),
            members=(member,),
            relation_provenance=(relation,),
        )


# --- FX-60H H3: query efficiency ---------------------------------------------


class _CountingNewsRepository:
    """Counts calls the production use case actually makes against
    its `_VintageLookup` dependency, delegating to a real
    `FakeNewsRepository` for behavior -- proves round trips stay O(1)
    regardless of how many items/groups exist."""

    def __init__(self, delegate: FakeNewsRepository) -> None:
        self._delegate = delegate
        self.batch_calls = 0

    async def latest_evidence_eligible_vintages_as_of(
        self,
        news_item_keys: tuple[str, ...],
        as_of: UtcTimestamp,
        *,
        include_backfill: bool = False,
    ) -> dict[str, NewsItemVintage]:
        self.batch_calls += 1
        return await self._delegate.latest_evidence_eligible_vintages_as_of(
            news_item_keys, as_of, include_backfill=include_backfill
        )


class _CountingSemanticRepository:
    def __init__(self, delegate: FakeNewsSemanticRepository) -> None:
        self._delegate = delegate
        self.batch_calls = 0

    async def latest_annotations_as_of(
        self, news_item_keys: tuple[str, ...], as_of: UtcTimestamp
    ) -> dict[str, NewsSemanticAnnotationVintage]:
        self.batch_calls += 1
        return await self._delegate.latest_annotations_as_of(news_item_keys, as_of)


class _CountingCanonicalizationRepository:
    def __init__(self, delegate: FakeNewsCanonicalizationRepository) -> None:
        self._delegate = delegate
        self.list_items_calls = 0
        self.list_relations_calls = 0

    async def list_items_seen_as_of(self, as_of: UtcTimestamp) -> tuple[NewsItem, ...]:
        self.list_items_calls += 1
        return await self._delegate.list_items_seen_as_of(as_of)

    async def list_latest_relation_states_as_of(
        self, as_of: UtcTimestamp
    ) -> tuple[NewsCanonicalRelationVintage, ...]:
        self.list_relations_calls += 1
        return await self._delegate.list_latest_relation_states_as_of(as_of)


def _populate_many_singleton_items(world: FakeWorld, count: int) -> None:
    for i in range(count):
        key = f"ITEM-{i:04d}"
        world.add_item(key, first_seen_at=_ts(9))
        world.add_annotation(key, availability=_ts(9, 1), classification=classification())


@pytest.mark.asyncio
@pytest.mark.parametrize("item_count", [1, 10, 50, 200])
async def test_round_trips_do_not_grow_with_item_population(item_count: int) -> None:
    world = FakeWorld()
    _populate_many_singleton_items(world, item_count)

    news_repo = _CountingNewsRepository(FakeNewsRepository(world))
    canon_repo = _CountingCanonicalizationRepository(FakeNewsCanonicalizationRepository(world))
    semantic_repo = _CountingSemanticRepository(FakeNewsSemanticRepository(world))
    get_snapshot = GetPairNewsEvidenceSnapshot(
        news_repo,
        canon_repo,  # type: ignore[arg-type]
        semantic_repo,
    )

    snapshot = await get_snapshot(EURUSD, _ts(0), _ts(10))

    assert snapshot.accounting.items_pit_visible == item_count
    assert canon_repo.list_items_calls == 1
    assert canon_repo.list_relations_calls == 1
    assert news_repo.batch_calls == 1
    assert semantic_repo.batch_calls == 1


# --- No-direction-field regression (Section 75) -----------------------------


@pytest.mark.parametrize(
    "dto_class",
    [NewsPairEvidenceSnapshot, NewsPairEvidenceGroup, NewsPairEvidenceMember],
)
def test_no_direction_sentiment_or_score_field_exists(dto_class: type) -> None:
    field_names = {f.name for f in dataclasses.fields(dto_class)}
    forbidden = {
        "direction",
        "sentiment",
        "stance",
        "bias",
        "bullish",
        "bearish",
        "support_score",
        "relevance_score",
        "importance",
        "importance_score",
        "impact",
        "impact_score",
        "severity",
        "urgency",
        "confidence",
        "duplicate_count",
        "evidence_strength",
        "duplicate_weight",
    }
    assert field_names.isdisjoint(forbidden)


# --- No-persistence / no-network contracts (Section 76/77) -----------------


def test_no_new_alembic_migration_for_pair_snapshot() -> None:
    versions_dir = pathlib.Path(__file__).resolve().parents[3] / "alembic" / "versions"
    matches = [p for p in versions_dir.glob("*.py") if "pair" in p.name.lower()]
    assert matches == []


def test_use_case_module_defines_no_orm_model_and_makes_no_network_calls() -> None:
    import forex_agent.application.use_cases.get_pair_news_evidence_snapshot as module

    assert module.__file__ is not None
    source = pathlib.Path(module.__file__).read_text()
    # A precise check for an actual SQLAlchemy IMPORT/ORM-base-class
    # usage -- not a bare "sqlalchemy" substring match, which would
    # also (falsely) trip on this module's own docstrings naming the
    # concrete `SqlAlchemyNewsRepository`/`SqlAlchemyNewsSemantic
    # Repository` classes that satisfy its narrow local Protocols.
    assert "import sqlalchemy" not in source.lower()
    assert "from sqlalchemy" not in source.lower()
    assert "Base)" not in source
    for forbidden_token in ("httpx", "requests.", "aiohttp", "urllib.request"):
        assert forbidden_token not in source


# --- Fail-closed structural checks (Section 53) -----------------------------


@pytest.mark.asyncio
async def test_malformed_publisher_entity_fails_closed() -> None:
    world = FakeWorld()
    world.add_item("A", first_seen_at=_ts(9))
    # Two SOURCE_PROFILE institution entities -- structurally malformed.
    malformed = NewsSemanticClassification(
        entities=(
            NewsEntityAnnotation(
                entity_type=NewsEntityType.INSTITUTION,
                entity_key="EUROPEAN_CENTRAL_BANK",
                evidence=(NewsEntityEvidenceKind.SOURCE_PROFILE,),
            ),
            NewsEntityAnnotation(
                entity_type=NewsEntityType.INSTITUTION,
                entity_key="FEDERAL_RESERVE",
                evidence=(NewsEntityEvidenceKind.SOURCE_PROFILE,),
            ),
            NewsEntityAnnotation(
                entity_type=NewsEntityType.JURISDICTION,
                entity_key="UNITED_STATES",
                evidence=(NewsEntityEvidenceKind.SOURCE_PROFILE,),
            ),
        ),
        topics=(),
        currency_relevance=(
            NewsCurrencyRelevance(
                currency_code="USD", reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,)
            ),
        ),
    )
    world.add_annotation("A", availability=_ts(9, 5), classification=malformed)

    get_snapshot = _make_snapshot_getter(world)
    with pytest.raises(NewsPairSnapshotConstructionError):
        await get_snapshot(EURUSD, _ts(0), _ts(10))
