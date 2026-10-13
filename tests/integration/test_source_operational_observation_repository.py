"""FX-63 Section 13.F: real-Postgres integration tests for `SqlAlchemy
SourceOperationalObservationRepository`, the new `SqlAlchemyNewsRepository`
batch content-lookup methods, and `GetSourceOperationalProfileAsOf`
end-to-end against real data -- append-only persistence, natural-key
uniqueness/idempotency (including concurrent duplicate delivery),
historical query ordering, real NewsItem vintage content metrics,
query-count sanity, and integration with FX-62's own PIT identity/
publisher resolution.

Requires a live Postgres with migration `d8995cb04276` applied (the
current head)."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.application.use_cases.get_source_operational_profile_as_of import (
    GetSourceOperationalProfileAsOf,
)
from forex_agent.application.use_cases.record_source_identity_vintage import (
    RecordSourceIdentityVintage,
)
from forex_agent.application.use_cases.record_source_operational_observation import (
    RecordSourceOperationalObservation,
    SourceOperationalObservationOutcome,
)
from forex_agent.application.use_cases.resolve_publisher_for_news_item_as_of import (
    PublisherResolutionStatus,
    ResolvePublisherForNewsItemAsOf,
)
from forex_agent.application.use_cases.resolve_source_identity_as_of import (
    ResolveSourceIdentityAsOf,
)
from forex_agent.domain.intelligence_source_kind import IntelligenceSourceKind
from forex_agent.domain.news_evidence_disposition import NewsEvidenceDisposition
from forex_agent.domain.news_item_vintage import NewsItemVintage
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.news_source_identity import NewsSourceIdentity
from forex_agent.domain.news_source_status import NewsSourceStatus
from forex_agent.domain.operational_metric_coverage import OperationalMetricCoverage
from forex_agent.domain.source_acquisition_outcome import SourceAcquisitionOutcome
from forex_agent.domain.source_evidence_kind import SourceEvidenceKind
from forex_agent.domain.source_provenance_evidence import SourceProvenanceEvidence
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.models.intelligence_source import IntelligenceSourceRow
from forex_agent.infrastructure.db.models.news_item import NewsItemRow
from forex_agent.infrastructure.db.models.news_item_vintage import NewsItemVintageRow
from forex_agent.infrastructure.db.models.news_source_mapping import NewsSourceMappingRow
from forex_agent.infrastructure.db.models.source_identity_vintage import SourceIdentityVintageRow
from forex_agent.infrastructure.db.models.source_operational_observation import (
    SourceOperationalObservationRow,
)
from forex_agent.infrastructure.db.news_repository import SqlAlchemyNewsRepository
from forex_agent.infrastructure.db.session import get_engine
from forex_agent.infrastructure.db.source_operational_observation_repository import (
    SqlAlchemySourceOperationalObservationRepository,
)
from forex_agent.infrastructure.db.source_registry_repository import (
    SqlAlchemySourceRegistryRepository,
)

TEST_SOURCE_KEY = "__fx63_repo_test__"
TEST_NEWS_SOURCE_KEY = "__fx63_repo_test_news__"


def _ts(hour: int, minute: int = 0) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, hour, minute, tzinfo=UTC))


def _identity(suffix: str, source_key: str = TEST_NEWS_SOURCE_KEY) -> NewsSourceIdentity:
    return NewsSourceIdentity(source_key=source_key, external_item_id=suffix)


def _evidence(description: str = "test") -> SourceProvenanceEvidence:
    return SourceProvenanceEvidence(
        evidence_kind=SourceEvidenceKind.ADAPTER_CONFIGURATION, description=description
    )


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    async with session_factory() as db_session:
        yield db_session

    async with session_factory() as cleanup_session:
        await cleanup_session.execute(
            delete(SourceOperationalObservationRow).where(
                SourceOperationalObservationRow.source_key.in_(
                    (TEST_SOURCE_KEY, TEST_NEWS_SOURCE_KEY)
                )
            )
        )
        await cleanup_session.execute(
            delete(SourceIdentityVintageRow).where(
                SourceIdentityVintageRow.source_key == TEST_SOURCE_KEY
            )
        )
        await cleanup_session.execute(
            delete(IntelligenceSourceRow).where(IntelligenceSourceRow.source_key == TEST_SOURCE_KEY)
        )
        item_keys = (
            (
                await cleanup_session.execute(
                    delete(NewsSourceMappingRow)
                    .where(
                        NewsSourceMappingRow.source_key.in_((TEST_SOURCE_KEY, TEST_NEWS_SOURCE_KEY))
                    )
                    .returning(NewsSourceMappingRow.news_item_key)
                )
            )
            .scalars()
            .all()
        )
        for key in item_keys:
            await cleanup_session.execute(
                delete(NewsItemVintageRow).where(NewsItemVintageRow.news_item_key == key)
            )
            await cleanup_session.execute(
                delete(NewsItemRow).where(NewsItemRow.news_item_key == key)
            )
        await cleanup_session.commit()


@pytest.fixture
def observation_repo(session: AsyncSession) -> SqlAlchemySourceOperationalObservationRepository:
    return SqlAlchemySourceOperationalObservationRepository(session)


@pytest.fixture
def news_repo(session: AsyncSession) -> SqlAlchemyNewsRepository:
    return SqlAlchemyNewsRepository(session)


@pytest.fixture
def registry_repo(session: AsyncSession) -> SqlAlchemySourceRegistryRepository:
    return SqlAlchemySourceRegistryRepository(session)


async def _make_news_item(
    news_repo: SqlAlchemyNewsRepository, suffix: str, *, source_key: str = TEST_NEWS_SOURCE_KEY
) -> str:
    registration = await news_repo._register_source_item_for_test_setup(
        _identity(suffix, source_key), _ts(8), NewsObservationMode.PROSPECTIVE
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
    return registration.news_item_key


# --- Append-only persistence / idempotency -----------------------------------


async def test_observation_persists_and_round_trips(
    observation_repo: SqlAlchemySourceOperationalObservationRepository,
) -> None:
    record = RecordSourceOperationalObservation(observation_repo)

    result = await record(
        source_key=TEST_SOURCE_KEY,
        source_channel="press_monetary",
        run_id="run-1",
        attempt_number=1,
        outcome=SourceAcquisitionOutcome.SUCCESS,
        availability=_ts(9),
        http_status=200,
    )

    assert result.outcome is SourceOperationalObservationOutcome.RECORDED
    fetched = await observation_repo.list_observations_for_source_as_of(
        TEST_SOURCE_KEY, _ts(0), _ts(12)
    )
    assert len(fetched) == 1
    assert fetched[0].outcome is SourceAcquisitionOutcome.SUCCESS


async def test_duplicate_natural_key_is_idempotent_real_postgres(
    observation_repo: SqlAlchemySourceOperationalObservationRepository,
) -> None:
    record = RecordSourceOperationalObservation(observation_repo)
    kwargs = {
        "source_key": TEST_SOURCE_KEY,
        "source_channel": "press_monetary",
        "run_id": "run-dup",
        "attempt_number": 1,
        "outcome": SourceAcquisitionOutcome.HTTP_FAILURE,
        "availability": _ts(9),
        "http_status": 503,
    }

    first = await record(**kwargs)  # type: ignore[arg-type]
    second = await record(**kwargs)  # type: ignore[arg-type]

    assert first.outcome is SourceOperationalObservationOutcome.RECORDED
    assert second.outcome is SourceOperationalObservationOutcome.DUPLICATE
    fetched = await observation_repo.list_observations_for_source_as_of(
        TEST_SOURCE_KEY, _ts(0), _ts(12)
    )
    assert len(fetched) == 1


async def test_concurrent_duplicate_event_insertion_is_safe(
    observation_repo: SqlAlchemySourceOperationalObservationRepository,
) -> None:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)

    async def _record_once() -> SourceOperationalObservationOutcome:
        async with session_factory() as own_session:
            own_repo = SqlAlchemySourceOperationalObservationRepository(own_session)
            record = RecordSourceOperationalObservation(own_repo)
            result = await record(
                source_key=TEST_SOURCE_KEY,
                source_channel="press_monetary",
                run_id="run-concurrent",
                attempt_number=1,
                outcome=SourceAcquisitionOutcome.SUCCESS,
                availability=_ts(9),
                http_status=200,
            )
            return result.outcome

    outcomes = await asyncio.gather(_record_once(), _record_once())

    assert sorted(o.value for o in outcomes) == sorted(
        [
            SourceOperationalObservationOutcome.RECORDED.value,
            SourceOperationalObservationOutcome.DUPLICATE.value,
        ]
    )
    async with session_factory() as check_session:
        check_repo = SqlAlchemySourceOperationalObservationRepository(check_session)
        fetched = await check_repo.list_observations_for_source_as_of(
            TEST_SOURCE_KEY, _ts(0), _ts(12)
        )
        assert len(fetched) == 1


async def test_observations_work_without_any_fx62_registration(
    observation_repo: SqlAlchemySourceOperationalObservationRepository,
) -> None:
    """Section 5/11's own explicit design requirement: acquisition
    instrumentation must keep recording regardless of whether FX-62's
    own bootstrap has ever registered this technical feed -- proven by
    recording successfully with NO `intelligence_sources` row at all
    for `TEST_SOURCE_KEY`."""
    record = RecordSourceOperationalObservation(observation_repo)

    result = await record(
        source_key=TEST_SOURCE_KEY,
        source_channel="press_monetary",
        run_id="run-no-fk",
        attempt_number=1,
        outcome=SourceAcquisitionOutcome.SUCCESS,
        availability=_ts(9),
        http_status=200,
    )

    assert result.outcome is SourceOperationalObservationOutcome.RECORDED


async def test_historical_query_ordering_is_availability_based(
    observation_repo: SqlAlchemySourceOperationalObservationRepository,
) -> None:
    record = RecordSourceOperationalObservation(observation_repo)
    await record(
        source_key=TEST_SOURCE_KEY,
        source_channel="press_monetary",
        run_id="run-a",
        attempt_number=1,
        outcome=SourceAcquisitionOutcome.SUCCESS,
        availability=_ts(10),
        http_status=200,
    )
    await record(
        source_key=TEST_SOURCE_KEY,
        source_channel="press_monetary",
        run_id="run-b",
        attempt_number=1,
        outcome=SourceAcquisitionOutcome.SUCCESS,
        availability=_ts(9),
        http_status=200,
    )

    at_930 = await observation_repo.list_observations_for_source_as_of(
        TEST_SOURCE_KEY, _ts(0), _ts(9, 30)
    )
    at_1030 = await observation_repo.list_observations_for_source_as_of(
        TEST_SOURCE_KEY, _ts(0), _ts(10, 30)
    )

    assert len(at_930) == 1
    assert at_930[0].run_id == "run-b"
    assert len(at_1030) == 2


# --- Real NewsItem vintage content metrics + query-count sanity -------------


async def test_real_newsitem_vintage_content_metrics_via_batch_methods(
    news_repo: SqlAlchemyNewsRepository,
) -> None:
    for i in range(5):
        await _make_news_item(news_repo, f"item{i}")

    item_keys = await news_repo.list_item_keys_for_source(TEST_NEWS_SOURCE_KEY)
    assert len(item_keys) == 5

    vintages_by_item = await news_repo.list_vintages_for_items(item_keys)
    assert len(vintages_by_item) == 5
    assert all(len(v) == 1 for v in vintages_by_item.values())


async def test_batch_content_lookup_is_constant_round_trips(
    news_repo: SqlAlchemyNewsRepository,
) -> None:
    """FX-60H's own lesson, reapplied here: the batch content lookup
    must not issue one round trip per item regardless of population
    size."""
    for i in range(10):
        await _make_news_item(news_repo, f"rt{i}")

    statement_count = {"count": 0}

    def _count_statement(*_args: object, **_kwargs: object) -> None:
        statement_count["count"] += 1

    sync_engine = get_engine().sync_engine
    event.listen(sync_engine, "before_cursor_execute", _count_statement)
    try:
        item_keys = await news_repo.list_item_keys_for_source(TEST_NEWS_SOURCE_KEY)
        await news_repo.list_vintages_for_items(item_keys)
    finally:
        event.remove(sync_engine, "before_cursor_execute", _count_statement)

    # Exactly 2 SELECTs (one per batch method) + their own commits --
    # never one round trip per item.
    assert statement_count["count"] <= 4


# --- GetSourceOperationalProfileAsOf end-to-end, with real FX-62 reuse ------


async def test_profile_end_to_end_with_real_fx62_identity_and_publisher(
    observation_repo: SqlAlchemySourceOperationalObservationRepository,
    news_repo: SqlAlchemyNewsRepository,
    registry_repo: SqlAlchemySourceRegistryRepository,
) -> None:
    item_key = await _make_news_item(news_repo, "profile1", source_key=TEST_SOURCE_KEY)
    record_observation = RecordSourceOperationalObservation(observation_repo)
    await record_observation(
        source_key=TEST_SOURCE_KEY,
        source_channel="test_channel",
        run_id="run-1",
        attempt_number=1,
        outcome=SourceAcquisitionOutcome.SUCCESS,
        availability=_ts(8),
        http_status=200,
    )
    record_identity = RecordSourceIdentityVintage(registry_repo)
    await record_identity(
        source_key=TEST_SOURCE_KEY,
        source_kind=IntelligenceSourceKind.TECHNICAL_FEED,
        registered_at=_ts(7),
        availability=_ts(7),
        algorithm_version="fx62_v1",
        display_name="Test Feed",
        aliases=(),
        authoritative_identifier=None,
        canonical_website=None,
        evidence=_evidence(),
    )

    get_profile = GetSourceOperationalProfileAsOf(
        observation_repo,
        news_repo,
        ResolveSourceIdentityAsOf(registry_repo),
        ResolvePublisherForNewsItemAsOf(registry_repo),
    )

    profile = await get_profile(TEST_SOURCE_KEY, _ts(0), _ts(12))

    assert profile.feed_display_name == "Test Feed"
    assert profile.acquisition.coverage is OperationalMetricCoverage.PARTIAL
    assert profile.acquisition.recorded_attempts == 1
    assert profile.content.distinct_items_known_as_of == 1
    # No PUBLISHER attribution was ever recorded for this item -- never
    # falls back to the technical feed's own identity.
    assert profile.publisher_resolution_status is PublisherResolutionStatus.NOT_RECORDED
    assert profile.publisher_source_key is None
    assert item_key  # the item exists and was counted above
