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
from forex_agent.application.use_cases.get_pair_news_evidence_snapshot import (
    SNAPSHOT_POLICY_VERSION,
    GetPairNewsEvidenceSnapshot,
    NewsPairEvidenceGroup,
    NewsPairEvidenceMember,
    NewsPairEvidenceSnapshot,
    NewsPairSemanticCoverage,
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

    async def list_annotation_vintages_for_item(self, news_item_key: str) -> object:
        raise NotImplementedError

    async def list_latest_annotation_states_as_of(self, as_of: UtcTimestamp) -> object:
        raise NotImplementedError

    async def add_annotation_vintage(self, vintage: object) -> object:
        raise NotImplementedError


def _make_snapshot_getter(world: FakeWorld) -> GetPairNewsEvidenceSnapshot:
    return GetPairNewsEvidenceSnapshot(
        FakeNewsRepository(world),  # type: ignore[arg-type]
        FakeNewsCanonicalizationRepository(world),  # type: ignore[arg-type]
        FakeNewsSemanticRepository(world),  # type: ignore[arg-type]
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
    assert "sqlalchemy" not in source.lower()
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
