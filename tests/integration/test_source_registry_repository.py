"""FX-62 Section 12.E: real-Postgres integration tests for `SqlAlchemy
SourceRegistryRepository` -- migration-created foreign-key/uniqueness
constraints, PIT identity/attribution resolution, the Section 9
publisher-correction worked example, and concurrent-write safety
through the recording use cases themselves (mirrors FX-58H/FX-59's own
`test_canonical_relation_concurrency.py`/`test_semantic_annotation_
concurrency.py` precedent exactly).

Requires a live Postgres with migration `e23aac921014` applied (the
current head)."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.application.ports.source_registry_repository import (
    IntelligenceSourceConflictError,
)
from forex_agent.application.use_cases.bootstrap_source_registry import BootstrapSourceRegistry
from forex_agent.application.use_cases.record_source_attribution import (
    OutOfOrderSourceAttributionError,
    RecordSourceAttribution,
    SourceAttributionOutcome,
)
from forex_agent.application.use_cases.record_source_identity_vintage import (
    RecordSourceIdentityVintage,
    SourceIdentityOutcome,
)
from forex_agent.application.use_cases.resolve_publisher_for_news_item_as_of import (
    PublisherResolutionStatus,
    ResolvePublisherForNewsItemAsOf,
)
from forex_agent.application.use_cases.resolve_source_identity_as_of import (
    ResolveSourceIdentityAsOf,
    SourceIdentityResolution,
)
from forex_agent.domain.intelligence_source import IntelligenceSource
from forex_agent.domain.intelligence_source_kind import IntelligenceSourceKind
from forex_agent.domain.news_evidence_disposition import NewsEvidenceDisposition
from forex_agent.domain.news_item_vintage import NewsItemVintage
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.news_semantic_classifying import NewsSemanticClassificationCandidate
from forex_agent.domain.news_source_identity import NewsSourceIdentity
from forex_agent.domain.news_source_status import NewsSourceStatus
from forex_agent.domain.source_attribution_role import SourceAttributionRole
from forex_agent.domain.source_attribution_status import SourceAttributionStatus
from forex_agent.domain.source_attribution_vintage import SourceAttributionVintage
from forex_agent.domain.source_evidence_kind import SourceEvidenceKind
from forex_agent.domain.source_identity_vintage import SourceIdentityVintage
from forex_agent.domain.source_provenance_evidence import SourceProvenanceEvidence
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.models.intelligence_source import IntelligenceSourceRow
from forex_agent.infrastructure.db.models.news_item import NewsItemRow
from forex_agent.infrastructure.db.models.news_item_vintage import NewsItemVintageRow
from forex_agent.infrastructure.db.models.news_source_mapping import NewsSourceMappingRow
from forex_agent.infrastructure.db.models.source_attribution_vintage import (
    SourceAttributionVintageRow,
)
from forex_agent.infrastructure.db.models.source_identity_vintage import SourceIdentityVintageRow
from forex_agent.infrastructure.db.news_repository import SqlAlchemyNewsRepository
from forex_agent.infrastructure.db.session import get_engine
from forex_agent.infrastructure.db.source_registry_repository import (
    SqlAlchemySourceRegistryRepository,
)

TEST_NEWS_SOURCE_KEY = "__fx62_repo_test_news__"
TEST_REGISTRY_PREFIX = "__fx62_repo_test__"


def _ts(hour: int, minute: int = 0) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, hour, minute, tzinfo=UTC))


def _future_bootstrap_ts() -> UtcTimestamp:
    """The real six-source bootstrap mapping table always touches the
    SAME global source_keys (FED, ECB, ...) as this project's own
    already-bootstrapped real production data (Section 13's own
    deliverable, intentionally left in place). A fixed historical
    `_ts()` would be rejected as backdated relative to that real
    identity's own `availability`, so bootstrap-specific tests use a
    timestamp safely after it instead."""
    return UtcTimestamp(datetime.now(UTC) + timedelta(days=3650))


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    async with session_factory() as db_session:
        yield db_session

    async with session_factory() as cleanup_session:
        await cleanup_session.execute(
            delete(SourceAttributionVintageRow).where(
                SourceAttributionVintageRow.news_item_key.startswith(TEST_NEWS_SOURCE_KEY)
            )
        )
        await cleanup_session.execute(
            delete(SourceAttributionVintageRow).where(
                SourceAttributionVintageRow.attributed_source_key.startswith(TEST_REGISTRY_PREFIX)
            )
        )
        await cleanup_session.execute(
            delete(SourceIdentityVintageRow).where(
                SourceIdentityVintageRow.source_key.startswith(TEST_REGISTRY_PREFIX)
            )
        )
        await cleanup_session.execute(
            delete(IntelligenceSourceRow).where(
                IntelligenceSourceRow.source_key.startswith(TEST_REGISTRY_PREFIX)
            )
        )
        await cleanup_session.execute(
            delete(NewsItemVintageRow).where(
                NewsItemVintageRow.news_item_key.startswith(TEST_NEWS_SOURCE_KEY)
            )
        )
        await cleanup_session.execute(
            delete(NewsSourceMappingRow).where(
                NewsSourceMappingRow.source_key == TEST_NEWS_SOURCE_KEY
            )
        )
        await cleanup_session.execute(
            delete(NewsItemRow).where(NewsItemRow.news_item_key.startswith(TEST_NEWS_SOURCE_KEY))
        )
        await cleanup_session.commit()


@pytest.fixture
def news_repo(session: AsyncSession) -> SqlAlchemyNewsRepository:
    return SqlAlchemyNewsRepository(session)


@pytest.fixture
def registry_repo(session: AsyncSession) -> SqlAlchemySourceRegistryRepository:
    return SqlAlchemySourceRegistryRepository(session)


async def _make_news_item(news_repo: SqlAlchemyNewsRepository, suffix: str) -> str:
    key = f"{TEST_NEWS_SOURCE_KEY}{suffix}"
    identity = NewsSourceIdentity(source_key=TEST_NEWS_SOURCE_KEY, external_item_id=suffix)
    registration = await news_repo._register_source_item_for_test_setup(
        identity, _ts(8), NewsObservationMode.PROSPECTIVE
    )
    vintage = NewsItemVintage(
        news_item_key=registration.news_item_key,
        revision_sequence=0,
        availability=_ts(8),
        observation_mode=NewsObservationMode.PROSPECTIVE,
        headline="H",
        source_channel="test_channel",
        observed_source_channels=("test_channel",),
        source_status=NewsSourceStatus.ACTIVE,
        evidence_disposition=NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
    )
    await news_repo.add_vintage(vintage)
    del key
    return registration.news_item_key


async def _append_revision(
    news_repo: SqlAlchemyNewsRepository, news_item_key: str, *, revision_sequence: int
) -> None:
    vintage = NewsItemVintage(
        news_item_key=news_item_key,
        revision_sequence=revision_sequence,
        availability=_ts(8, 30),
        observation_mode=NewsObservationMode.PROSPECTIVE,
        headline="H (updated)",
        source_channel="test_channel",
        observed_source_channels=("test_channel",),
        source_status=NewsSourceStatus.ACTIVE,
        evidence_disposition=NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
    )
    await news_repo.add_vintage(vintage)


def _evidence(description: str = "test evidence") -> SourceProvenanceEvidence:
    return SourceProvenanceEvidence(
        evidence_kind=SourceEvidenceKind.ADAPTER_CONFIGURATION, description=description
    )


# --- Registration / idempotency / kind conflict -----------------------------


async def test_register_source_creates_source_and_first_vintage(
    registry_repo: SqlAlchemySourceRegistryRepository,
) -> None:
    source_key = f"{TEST_REGISTRY_PREFIX}ORG1"
    source = IntelligenceSource(
        source_key=source_key, source_kind=IntelligenceSourceKind.ORGANIZATION, registered_at=_ts(9)
    )
    vintage = SourceIdentityVintage(
        source_key=source_key,
        revision_sequence=0,
        availability=_ts(9),
        algorithm_version="fx62_v1",
        display_name="Test Org",
        aliases=(),
        authoritative_identifier=None,
        canonical_website=None,
        evidence=_evidence(),
    )

    result = await registry_repo.register_source_with_first_identity_vintage(source, vintage)

    assert result.created is True
    stored = await registry_repo.get_source(source_key)
    assert stored == source


async def test_register_source_is_idempotent_on_exact_retry(
    registry_repo: SqlAlchemySourceRegistryRepository,
) -> None:
    source_key = f"{TEST_REGISTRY_PREFIX}ORG2"
    source = IntelligenceSource(
        source_key=source_key, source_kind=IntelligenceSourceKind.ORGANIZATION, registered_at=_ts(9)
    )
    vintage = SourceIdentityVintage(
        source_key=source_key,
        revision_sequence=0,
        availability=_ts(9),
        algorithm_version="fx62_v1",
        display_name="Test Org",
        aliases=(),
        authoritative_identifier=None,
        canonical_website=None,
        evidence=_evidence(),
    )
    first = await registry_repo.register_source_with_first_identity_vintage(source, vintage)
    second = await registry_repo.register_source_with_first_identity_vintage(source, vintage)

    assert first.created is True
    assert second.created is False
    assert len(await registry_repo.list_identity_vintages_for_source(source_key)) == 1


async def test_kind_conflict_is_rejected(
    registry_repo: SqlAlchemySourceRegistryRepository,
) -> None:
    source_key = f"{TEST_REGISTRY_PREFIX}ORG3"
    org = IntelligenceSource(
        source_key=source_key, source_kind=IntelligenceSourceKind.ORGANIZATION, registered_at=_ts(9)
    )
    vintage = SourceIdentityVintage(
        source_key=source_key,
        revision_sequence=0,
        availability=_ts(9),
        algorithm_version="fx62_v1",
        display_name="Test Org",
        aliases=(),
        authoritative_identifier=None,
        canonical_website=None,
        evidence=_evidence(),
    )
    await registry_repo.register_source_with_first_identity_vintage(org, vintage)

    feed = IntelligenceSource(
        source_key=source_key,
        source_kind=IntelligenceSourceKind.TECHNICAL_FEED,
        registered_at=_ts(9),
    )
    with pytest.raises(IntelligenceSourceConflictError):
        await registry_repo.register_source_with_first_identity_vintage(feed, vintage)


# --- Foreign-key integrity ---------------------------------------------------


async def test_identity_vintage_requires_existing_source_fk(
    registry_repo: SqlAlchemySourceRegistryRepository,
) -> None:
    orphan_vintage = SourceIdentityVintage(
        source_key=f"{TEST_REGISTRY_PREFIX}NEVER_REGISTERED",
        revision_sequence=0,
        availability=_ts(9),
        algorithm_version="fx62_v1",
        display_name="Orphan",
        aliases=(),
        authoritative_identifier=None,
        canonical_website=None,
        evidence=_evidence(),
    )
    with pytest.raises(IntegrityError):
        await registry_repo.add_identity_vintage(orphan_vintage)


async def test_attribution_requires_existing_news_item_fk(
    registry_repo: SqlAlchemySourceRegistryRepository,
) -> None:
    orphan_attribution = SourceAttributionVintage(
        news_item_key=f"{TEST_NEWS_SOURCE_KEY}NEVER_REGISTERED",
        role=SourceAttributionRole.PUBLISHER,
        revision_sequence=0,
        availability=_ts(9),
        algorithm_version="fx62_v1",
        status=SourceAttributionStatus.UNRESOLVED,
        attributed_source_key=None,
        evidence_basis_revision_sequence=0,
        evidence=_evidence(),
    )
    with pytest.raises(IntegrityError):
        await registry_repo.add_attribution_vintage(orphan_attribution)


async def test_attribution_requires_existing_attributed_source_fk(
    registry_repo: SqlAlchemySourceRegistryRepository,
    news_repo: SqlAlchemyNewsRepository,
) -> None:
    item = await _make_news_item(news_repo, "fk1")
    attribution = SourceAttributionVintage(
        news_item_key=item,
        role=SourceAttributionRole.PUBLISHER,
        revision_sequence=0,
        availability=_ts(9),
        algorithm_version="fx62_v1",
        status=SourceAttributionStatus.CONFIRMED,
        attributed_source_key=f"{TEST_REGISTRY_PREFIX}NEVER_REGISTERED",
        evidence_basis_revision_sequence=0,
        evidence=_evidence(),
    )
    with pytest.raises(IntegrityError):
        await registry_repo.add_attribution_vintage(attribution)


# --- PIT identity resolution --------------------------------------------------


async def test_pit_identity_resolution_real_postgres(
    registry_repo: SqlAlchemySourceRegistryRepository,
) -> None:
    source_key = f"{TEST_REGISTRY_PREFIX}PIT1"
    record_identity = RecordSourceIdentityVintage(registry_repo)
    await record_identity(
        source_key=source_key,
        source_kind=IntelligenceSourceKind.ORGANIZATION,
        registered_at=_ts(10),
        availability=_ts(10),
        algorithm_version="fx62_v1",
        display_name="Example Org",
        aliases=(),
        authoritative_identifier=None,
        canonical_website=None,
        evidence=_evidence(),
    )
    resolve = ResolveSourceIdentityAsOf(registry_repo)

    before = await resolve(source_key, _ts(9))
    at = await resolve(source_key, _ts(10))
    after = await resolve(source_key, _ts(11))

    assert before.resolution is SourceIdentityResolution.NOT_KNOWN
    assert at.resolution is SourceIdentityResolution.KNOWN
    assert after.resolution is SourceIdentityResolution.KNOWN


# --- Section 9: publisher-correction worked example --------------------------


async def test_publisher_correction_worked_example_real_postgres(
    registry_repo: SqlAlchemySourceRegistryRepository,
    news_repo: SqlAlchemyNewsRepository,
) -> None:
    """T1: unconfirmed publisher. T2: F -> A. T3: corrected to B. T4: a
    newly observed item uses the mapping applicable at ITS OWN PIT. A
    historical snapshot at T2 must continue returning A after T3."""
    item = await _make_news_item(news_repo, "corr1")
    org_a = f"{TEST_REGISTRY_PREFIX}ORG_A"
    org_b = f"{TEST_REGISTRY_PREFIX}ORG_B"
    record_identity = RecordSourceIdentityVintage(registry_repo)
    for org_key, name in ((org_a, "Organization A"), (org_b, "Organization B")):
        await record_identity(
            source_key=org_key,
            source_kind=IntelligenceSourceKind.ORGANIZATION,
            registered_at=_ts(8),
            availability=_ts(8),
            algorithm_version="fx62_v1",
            display_name=name,
            aliases=(),
            authoritative_identifier=None,
            canonical_website=None,
            evidence=_evidence(f"registering {name}"),
        )

    record_attribution = RecordSourceAttribution(registry_repo)
    resolve_publisher = ResolvePublisherForNewsItemAsOf(registry_repo)

    # T1: unresolved.
    t1 = _ts(9)
    await record_attribution(
        news_item_key=item,
        role=SourceAttributionRole.PUBLISHER,
        availability=t1,
        algorithm_version="fx62_v1",
        status=SourceAttributionStatus.UNRESOLVED,
        attributed_source_key=None,
        evidence_basis_revision_sequence=0,
        evidence=_evidence("T1: not yet confirmed"),
    )

    # T2: confirmed -> A.
    t2 = _ts(10)
    await record_attribution(
        news_item_key=item,
        role=SourceAttributionRole.PUBLISHER,
        availability=t2,
        algorithm_version="fx62_v1",
        status=SourceAttributionStatus.CONFIRMED,
        attributed_source_key=org_a,
        evidence_basis_revision_sequence=0,
        evidence=_evidence("T2: confirmed as A"),
    )

    # T3: correction -> B.
    t3 = _ts(11)
    await record_attribution(
        news_item_key=item,
        role=SourceAttributionRole.PUBLISHER,
        availability=t3,
        algorithm_version="fx62_v1",
        status=SourceAttributionStatus.CONFIRMED,
        attributed_source_key=org_b,
        evidence_basis_revision_sequence=0,
        evidence=_evidence("T3: correction, A was wrong, actually B"),
        corrects_revision_sequence=1,
    )

    at_t1 = await resolve_publisher(item, t1)
    at_t2 = await resolve_publisher(item, t2)
    at_t3 = await resolve_publisher(item, t3)

    assert at_t1.status is PublisherResolutionStatus.UNRESOLVED
    assert at_t2.status is PublisherResolutionStatus.CONFIRMED
    assert at_t2.publisher is not None and at_t2.publisher.source_key == org_a
    assert at_t3.status is PublisherResolutionStatus.CONFIRMED
    assert at_t3.publisher is not None and at_t3.publisher.source_key == org_b

    # Re-querying T2 AGAIN, after T3 was recorded, must be unchanged.
    at_t2_again = await resolve_publisher(item, t2)
    assert at_t2_again.status is PublisherResolutionStatus.CONFIRMED
    assert at_t2_again.publisher is not None and at_t2_again.publisher.source_key == org_a


async def test_out_of_order_attribution_rejected_real_postgres(
    registry_repo: SqlAlchemySourceRegistryRepository,
    news_repo: SqlAlchemyNewsRepository,
) -> None:
    item = await _make_news_item(news_repo, "ooo1")
    record_attribution = RecordSourceAttribution(registry_repo)
    await record_attribution(
        news_item_key=item,
        role=SourceAttributionRole.PUBLISHER,
        availability=_ts(10),
        algorithm_version="fx62_v1",
        status=SourceAttributionStatus.UNRESOLVED,
        attributed_source_key=None,
        evidence_basis_revision_sequence=0,
        evidence=_evidence(),
    )

    with pytest.raises(OutOfOrderSourceAttributionError):
        await record_attribution(
            news_item_key=item,
            role=SourceAttributionRole.PUBLISHER,
            availability=_ts(9),
            algorithm_version="fx62_v1",
            status=SourceAttributionStatus.UNRESOLVED,
            attributed_source_key=None,
            evidence_basis_revision_sequence=0,
            evidence=_evidence("too late"),
        )


async def test_new_item_revision_requires_a_vintage_before_attribution(
    registry_repo: SqlAlchemySourceRegistryRepository,
    news_repo: SqlAlchemyNewsRepository,
) -> None:
    """T4 from the Section 9 worked example: a NEW item arriving
    through a feed uses the mapping applicable to its OWN PIT state --
    confirmed by attributing a second, later-appended item revision
    against the SAME already-confirmed organization."""
    item = await _make_news_item(news_repo, "t4item")
    org_key = f"{TEST_REGISTRY_PREFIX}ORG_T4"
    record_identity = RecordSourceIdentityVintage(registry_repo)
    await record_identity(
        source_key=org_key,
        source_kind=IntelligenceSourceKind.ORGANIZATION,
        registered_at=_ts(8),
        availability=_ts(8),
        algorithm_version="fx62_v1",
        display_name="Org T4",
        aliases=(),
        authoritative_identifier=None,
        canonical_website=None,
        evidence=_evidence(),
    )
    await _append_revision(news_repo, item, revision_sequence=1)

    record_attribution = RecordSourceAttribution(registry_repo)
    result = await record_attribution(
        news_item_key=item,
        role=SourceAttributionRole.PUBLISHER,
        availability=_ts(9, 30),
        algorithm_version="fx62_v1",
        status=SourceAttributionStatus.CONFIRMED,
        attributed_source_key=org_key,
        evidence_basis_revision_sequence=1,
        evidence=_evidence("T4: new revision, current mapping applied"),
    )

    assert result.outcome is SourceAttributionOutcome.CREATED


# --- Concurrency (mirrors FX-58H/FX-59's own established pattern) -----------


async def test_concurrent_identical_registration_one_created_one_unchanged(
    news_repo: SqlAlchemyNewsRepository,
) -> None:
    source_key = f"{TEST_REGISTRY_PREFIX}CONC1"
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)

    async def _register() -> SourceIdentityOutcome:
        async with session_factory() as own_session:
            own_repo = SqlAlchemySourceRegistryRepository(own_session)
            record = RecordSourceIdentityVintage(own_repo)
            result = await record(
                source_key=source_key,
                source_kind=IntelligenceSourceKind.ORGANIZATION,
                registered_at=_ts(9),
                availability=_ts(9),
                algorithm_version="fx62_v1",
                display_name="Concurrent Org",
                aliases=(),
                authoritative_identifier=None,
                canonical_website=None,
                evidence=_evidence(),
            )
            return result.outcome

    outcomes = await asyncio.gather(_register(), _register())

    assert sorted(o.value for o in outcomes) == sorted(
        [SourceIdentityOutcome.CREATED.value, SourceIdentityOutcome.UNCHANGED.value]
    )

    async with session_factory() as check_session:
        check_repo = SqlAlchemySourceRegistryRepository(check_session)
        stored = await check_repo.list_identity_vintages_for_source(source_key)
        assert len(stored) == 1


class _StubCandidateLookup:
    """Minimal `_CandidateLookup`-conforming stub naming ONE real,
    already-persisted news item under the FED feed key, so a real
    `BootstrapSourceRegistry` run exercises the real repository without
    needing full FX-59 semantic-annotation setup."""

    def __init__(self, news_item_key: str) -> None:
        self._news_item_key = news_item_key

    async def list_candidates_as_of(
        self, as_of: UtcTimestamp, *, include_backfill: bool = False
    ) -> tuple[NewsSemanticClassificationCandidate, ...]:
        return (
            NewsSemanticClassificationCandidate(
                news_item_key=self._news_item_key,
                source_key="FED",
                basis_news_item_revision_sequence=0,
                basis_availability=_ts(8),
                headline="H",
                summary=None,
                body_text=None,
                source_content_type=None,
                source_channel="test_channel",
            ),
        )


async def test_repeated_bootstrap_against_real_postgres_is_idempotent(
    registry_repo: SqlAlchemySourceRegistryRepository,
    news_repo: SqlAlchemyNewsRepository,
) -> None:
    item = await _make_news_item(news_repo, "bootstrap1")
    bootstrap = BootstrapSourceRegistry(
        RecordSourceIdentityVintage(registry_repo),
        RecordSourceAttribution(registry_repo),
        _StubCandidateLookup(item),
    )
    bootstrap_at = _future_bootstrap_ts()

    first = await bootstrap(bootstrap_at)
    second = await bootstrap(bootstrap_at)
    third = await bootstrap(bootstrap_at)

    assert first.total_attributions_created == 1
    assert second.feed_identities_created == 0
    assert second.total_attributions_created == 0
    assert second.total_attributions_unchanged == 1
    assert third.total_attributions_unchanged == 1

    resolve_publisher = ResolvePublisherForNewsItemAsOf(registry_repo)
    resolution = await resolve_publisher(item, bootstrap_at)
    assert resolution.status is PublisherResolutionStatus.CONFIRMED
    assert resolution.publisher is not None
    assert resolution.publisher.source_key == "FEDERAL_RESERVE"


async def test_concurrent_bootstrap_against_real_postgres_is_safe(
    news_repo: SqlAlchemyNewsRepository,
) -> None:
    item = await _make_news_item(news_repo, "bootstrap2")
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    bootstrap_at = _future_bootstrap_ts()

    async def _run_bootstrap() -> None:
        async with session_factory() as own_session:
            own_repo = SqlAlchemySourceRegistryRepository(own_session)
            bootstrap = BootstrapSourceRegistry(
                RecordSourceIdentityVintage(own_repo),
                RecordSourceAttribution(own_repo),
                _StubCandidateLookup(item),
            )
            await bootstrap(bootstrap_at)

    await asyncio.gather(_run_bootstrap(), _run_bootstrap())

    async with session_factory() as check_session:
        check_repo = SqlAlchemySourceRegistryRepository(check_session)
        assert len(await check_repo.list_sources()) == 12
        resolve_publisher = ResolvePublisherForNewsItemAsOf(check_repo)
        resolution = await resolve_publisher(item, bootstrap_at)
        assert resolution.status is PublisherResolutionStatus.CONFIRMED
        assert resolution.publisher is not None
        assert resolution.publisher.source_key == "FEDERAL_RESERVE"
