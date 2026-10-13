"""FX-64 Section 17.E: real-Postgres integration tests for `SqlAlchemy
StructuredForecastRepository` -- migration-created foreign-key/
uniqueness constraints, idempotent recording, exact NewsItemVintage
basis-pinning, PIT repository reads, append-only revisions, the
production-vs-retrospective-research separation (Section 7), full-
history determinism, concurrent insert safety, and the "no write
survives a rejected candidate" guarantee.

Requires a live Postgres with migration `afb65123d185` applied (the
current head)."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.application.use_cases.record_source_identity_vintage import (
    RecordSourceIdentityVintage,
)
from forex_agent.application.use_cases.record_structured_forecast import (
    RecordStructuredForecast,
    StructuredForecastOutcome,
)
from forex_agent.application.use_cases.validate_structured_forecast_candidate import (
    StructuredForecastCandidate,
)
from forex_agent.domain.forecast_attribution_kind import ForecastAttributionKind
from forex_agent.domain.forecast_capture_eligibility import ForecastCaptureEligibility
from forex_agent.domain.forecast_evidence_kind import ForecastEvidenceKind
from forex_agent.domain.forecast_provenance_mode import ForecastProvenanceMode
from forex_agent.domain.forecast_target_period_kind import ForecastTargetPeriodKind
from forex_agent.domain.forecast_type import ForecastType
from forex_agent.domain.intelligence_source_kind import IntelligenceSourceKind
from forex_agent.domain.news_evidence_disposition import NewsEvidenceDisposition
from forex_agent.domain.news_item_vintage import NewsItemVintage
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.news_source_identity import NewsSourceIdentity
from forex_agent.domain.news_source_status import NewsSourceStatus
from forex_agent.domain.source_evidence_kind import SourceEvidenceKind
from forex_agent.domain.source_provenance_evidence import SourceProvenanceEvidence
from forex_agent.domain.structured_forecast_vintage import StructuredForecastVintage
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.models.forecast_claim import ForecastClaimRow
from forex_agent.infrastructure.db.models.intelligence_source import IntelligenceSourceRow
from forex_agent.infrastructure.db.models.news_item import NewsItemRow
from forex_agent.infrastructure.db.models.news_item_vintage import NewsItemVintageRow
from forex_agent.infrastructure.db.models.news_source_mapping import NewsSourceMappingRow
from forex_agent.infrastructure.db.models.source_identity_vintage import SourceIdentityVintageRow
from forex_agent.infrastructure.db.models.structured_forecast_vintage import (
    StructuredForecastVintageRow,
)
from forex_agent.infrastructure.db.news_repository import SqlAlchemyNewsRepository
from forex_agent.infrastructure.db.session import get_engine
from forex_agent.infrastructure.db.source_registry_repository import (
    SqlAlchemySourceRegistryRepository,
)
from forex_agent.infrastructure.db.structured_forecast_repository import (
    SqlAlchemyStructuredForecastRepository,
)

TEST_CLAIM_PREFIX = "__fx64_repo_test__"
TEST_PUBLISHER_KEY = "__fx64_repo_test_publisher__"
TEST_NEWS_SOURCE_KEY = "__fx64_repo_test_news__"


def _ts(hour: int, minute: int = 0, day: int = 1, month: int = 1, year: int = 2026) -> UtcTimestamp:
    return UtcTimestamp(datetime(year, month, day, hour, minute, tzinfo=UTC))


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
            delete(StructuredForecastVintageRow).where(
                StructuredForecastVintageRow.claim_key.startswith(TEST_CLAIM_PREFIX)
            )
        )
        await cleanup_session.execute(
            delete(ForecastClaimRow).where(ForecastClaimRow.claim_key.startswith(TEST_CLAIM_PREFIX))
        )
        await cleanup_session.execute(
            delete(SourceIdentityVintageRow).where(
                SourceIdentityVintageRow.source_key == TEST_PUBLISHER_KEY
            )
        )
        await cleanup_session.execute(
            delete(IntelligenceSourceRow).where(
                IntelligenceSourceRow.source_key == TEST_PUBLISHER_KEY
            )
        )
        item_keys = (
            (
                await cleanup_session.execute(
                    delete(NewsSourceMappingRow)
                    .where(NewsSourceMappingRow.source_key == TEST_NEWS_SOURCE_KEY)
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
def forecast_repo(session: AsyncSession) -> SqlAlchemyStructuredForecastRepository:
    return SqlAlchemyStructuredForecastRepository(session)


@pytest.fixture
def news_repo(session: AsyncSession) -> SqlAlchemyNewsRepository:
    return SqlAlchemyNewsRepository(session)


@pytest.fixture
def registry_repo(session: AsyncSession) -> SqlAlchemySourceRegistryRepository:
    return SqlAlchemySourceRegistryRepository(session)


async def _ensure_publisher_registered(registry_repo: SqlAlchemySourceRegistryRepository) -> None:
    record_identity = RecordSourceIdentityVintage(registry_repo)
    await record_identity(
        source_key=TEST_PUBLISHER_KEY,
        source_kind=IntelligenceSourceKind.ORGANIZATION,
        registered_at=_ts(8),
        availability=_ts(8),
        algorithm_version="fx62_v1",
        display_name="Test Publisher Org",
        aliases=(),
        authoritative_identifier=None,
        canonical_website=None,
        evidence=_evidence(),
    )


async def _make_news_item(news_repo: SqlAlchemyNewsRepository, suffix: str) -> str:
    registration = await news_repo._register_source_item_for_test_setup(
        NewsSourceIdentity(source_key=TEST_NEWS_SOURCE_KEY, external_item_id=suffix),
        _ts(8),
        NewsObservationMode.PROSPECTIVE,
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


def _candidate(claim_suffix: str, **overrides: object) -> StructuredForecastCandidate:
    defaults: dict[str, object] = {
        "claim_key": f"{TEST_CLAIM_PREFIX}{claim_suffix}",
        "availability": _ts(9),
        "algorithm_version": "fx64_v1",
        "forecast_type": ForecastType.NUMERIC_POINT,
        "target_key": "EA_HICP_YOY_ANNUAL_AVERAGE",
        "target_period_kind": ForecastTargetPeriodKind.CALENDAR_YEAR,
        "calendar_year": 2025,
        "attribution_kind": ForecastAttributionKind.AGGREGATE_SURVEY_CONSENSUS,
        "publisher_source_key": TEST_PUBLISHER_KEY,
        "evidence_kind": ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
        "evidence_description": "test evidence",
        "document_identifier": "DOC-1",
        "provenance_mode": ForecastProvenanceMode.PRODUCTION_OBSERVED,
        "numeric_value": Decimal("1.9"),
        "unit": "PERCENT_YOY",
    }
    defaults.update(overrides)
    return StructuredForecastCandidate(**defaults)  # type: ignore[arg-type]


# --- Registration / idempotency ----------------------------------------------


async def test_first_registration_creates_claim_and_vintage(
    forecast_repo: SqlAlchemyStructuredForecastRepository,
    registry_repo: SqlAlchemySourceRegistryRepository,
) -> None:
    await _ensure_publisher_registered(registry_repo)
    record = RecordStructuredForecast(forecast_repo)

    result = await record(_candidate("reg1"), registered_at=_ts(9))

    assert result.outcome is StructuredForecastOutcome.CREATED
    claim = await forecast_repo.get_claim(f"{TEST_CLAIM_PREFIX}reg1")
    assert claim is not None


async def test_idempotent_exact_repeat(
    forecast_repo: SqlAlchemyStructuredForecastRepository,
    registry_repo: SqlAlchemySourceRegistryRepository,
) -> None:
    await _ensure_publisher_registered(registry_repo)
    record = RecordStructuredForecast(forecast_repo)
    await record(_candidate("reg2"), registered_at=_ts(9))

    result = await record(_candidate("reg2", availability=_ts(10)), registered_at=_ts(9))

    assert result.outcome is StructuredForecastOutcome.UNCHANGED
    assert len(await forecast_repo.list_vintages_for_claim(f"{TEST_CLAIM_PREFIX}reg2")) == 1


# --- Foreign-key integrity -----------------------------------------------------


async def test_add_vintage_requires_existing_claim_fk(
    forecast_repo: SqlAlchemyStructuredForecastRepository,
    registry_repo: SqlAlchemySourceRegistryRepository,
) -> None:
    await _ensure_publisher_registered(registry_repo)
    from forex_agent.domain.forecast_attribution import ForecastAttribution
    from forex_agent.domain.forecast_evidence_reference import ForecastEvidenceReference
    from forex_agent.domain.forecast_target_period import ForecastTargetPeriod

    orphan = StructuredForecastVintage(
        claim_key=f"{TEST_CLAIM_PREFIX}NEVER_REGISTERED",
        revision_sequence=0,
        availability=_ts(9),
        algorithm_version="fx64_v1",
        forecast_type=ForecastType.NUMERIC_POINT,
        target_key="EA_HICP_YOY_ANNUAL_AVERAGE",
        target_period=ForecastTargetPeriod(
            period_kind=ForecastTargetPeriodKind.CALENDAR_YEAR, calendar_year=2025
        ),
        attribution=ForecastAttribution(
            kind=ForecastAttributionKind.AGGREGATE_SURVEY_CONSENSUS,
            publisher_source_key=TEST_PUBLISHER_KEY,
        ),
        provenance_mode=ForecastProvenanceMode.PRODUCTION_OBSERVED,
        evidence=ForecastEvidenceReference(
            evidence_kind=ForecastEvidenceKind.EXTERNAL_DOCUMENT_REFERENCE,
            description="test",
            document_identifier="DOC-X",
        ),
        numeric_value=Decimal("1.9"),
        unit="PERCENT_YOY",
    )
    with pytest.raises(IntegrityError):
        await forecast_repo.add_vintage(orphan)


async def test_publisher_source_key_requires_existing_fx62_identity(
    forecast_repo: SqlAlchemyStructuredForecastRepository,
) -> None:
    """No FX-62 registration exists for this publisher key."""
    record = RecordStructuredForecast(forecast_repo)

    with pytest.raises(IntegrityError):
        await record(
            _candidate("fk_pub", publisher_source_key="__never_registered_publisher__"),
            registered_at=_ts(9),
        )


# --- Exact NewsItemVintage basis-pinning --------------------------------------


async def test_news_item_vintage_basis_pins_exact_vintage(
    forecast_repo: SqlAlchemyStructuredForecastRepository,
    registry_repo: SqlAlchemySourceRegistryRepository,
    news_repo: SqlAlchemyNewsRepository,
) -> None:
    await _ensure_publisher_registered(registry_repo)
    item_key = await _make_news_item(news_repo, "basis1")
    record = RecordStructuredForecast(forecast_repo)

    result = await record(
        _candidate(
            "basis_claim",
            evidence_kind=ForecastEvidenceKind.NEWS_ITEM_VINTAGE_BASIS,
            document_identifier=None,
            news_item_key=item_key,
            basis_revision_sequence=0,
        ),
        registered_at=_ts(9),
    )

    assert result.outcome is StructuredForecastOutcome.CREATED
    assert result.vintage is not None
    assert result.vintage.evidence.news_item_key == item_key


async def test_news_item_vintage_basis_requires_existing_vintage_fk(
    forecast_repo: SqlAlchemyStructuredForecastRepository,
    registry_repo: SqlAlchemySourceRegistryRepository,
    news_repo: SqlAlchemyNewsRepository,
) -> None:
    await _ensure_publisher_registered(registry_repo)
    item_key = await _make_news_item(news_repo, "basis2")
    record = RecordStructuredForecast(forecast_repo)

    with pytest.raises(IntegrityError):
        await record(
            _candidate(
                "basis_claim2",
                evidence_kind=ForecastEvidenceKind.NEWS_ITEM_VINTAGE_BASIS,
                document_identifier=None,
                news_item_key=item_key,
                basis_revision_sequence=99,  # never-existing revision
            ),
            registered_at=_ts(9),
        )


# --- PIT reads / production-vs-research separation ---------------------------


async def test_pit_production_read_real_postgres(
    forecast_repo: SqlAlchemyStructuredForecastRepository,
    registry_repo: SqlAlchemySourceRegistryRepository,
) -> None:
    await _ensure_publisher_registered(registry_repo)
    record = RecordStructuredForecast(forecast_repo)
    await record(_candidate("pit1", availability=_ts(10)), registered_at=_ts(10))

    before = await forecast_repo.latest_production_observed_vintage_as_of(
        f"{TEST_CLAIM_PREFIX}pit1", _ts(9)
    )
    after = await forecast_repo.latest_production_observed_vintage_as_of(
        f"{TEST_CLAIM_PREFIX}pit1", _ts(11)
    )

    assert before is None
    assert after is not None


async def test_retrospective_vintage_invisible_to_production_read(
    forecast_repo: SqlAlchemyStructuredForecastRepository,
    registry_repo: SqlAlchemySourceRegistryRepository,
) -> None:
    await _ensure_publisher_registered(registry_repo)
    record = RecordStructuredForecast(forecast_repo)
    await record(
        _candidate(
            "retro1",
            provenance_mode=ForecastProvenanceMode.RETROSPECTIVE_RESEARCH,
            availability=_ts(10, year=2026),
            original_publication_at=_ts(8, year=2023),
        ),
        registered_at=_ts(10, year=2026),
    )

    production = await forecast_repo.latest_production_observed_vintage_as_of(
        f"{TEST_CLAIM_PREFIX}retro1", _ts(10, year=2027)
    )
    research = await forecast_repo.latest_vintage_as_of_for_research(
        f"{TEST_CLAIM_PREFIX}retro1", _ts(10, year=2027)
    )

    assert production is None
    assert research is not None
    assert research.provenance_mode is ForecastProvenanceMode.RETROSPECTIVE_RESEARCH


# --- Full-history determinism / append-only revisions -------------------------


async def test_append_only_revision_real_postgres(
    forecast_repo: SqlAlchemyStructuredForecastRepository,
    registry_repo: SqlAlchemySourceRegistryRepository,
) -> None:
    await _ensure_publisher_registered(registry_repo)
    record = RecordStructuredForecast(forecast_repo)
    await record(_candidate("rev1"), registered_at=_ts(9))

    result = await record(
        _candidate(
            "rev1",
            availability=_ts(10),
            numeric_value=Decimal("2.2"),
            document_identifier="DOC-2",
        ),
        registered_at=_ts(9),
    )

    assert result.outcome is StructuredForecastOutcome.REVISION_ADDED
    vintages = await forecast_repo.list_vintages_for_claim(f"{TEST_CLAIM_PREFIX}rev1")
    assert len(vintages) == 2


async def test_full_history_determinism_real_postgres(
    forecast_repo: SqlAlchemyStructuredForecastRepository,
    registry_repo: SqlAlchemySourceRegistryRepository,
) -> None:
    await _ensure_publisher_registered(registry_repo)
    record = RecordStructuredForecast(forecast_repo)
    await record(_candidate("det1", document_identifier="SAME-DOC"), registered_at=_ts(9))
    await record(
        _candidate(
            "det1",
            availability=_ts(10),
            numeric_value=Decimal("2.2"),
            document_identifier="OTHER-DOC",
        ),
        registered_at=_ts(9),
    )

    from forex_agent.application.use_cases.record_structured_forecast import (
        StructuredForecastDeterminismError,
    )

    with pytest.raises(StructuredForecastDeterminismError):
        await record(
            _candidate(
                "det1",
                availability=_ts(11),
                numeric_value=Decimal("9.9"),
                document_identifier="SAME-DOC",
            ),
            registered_at=_ts(9),
        )


# --- Concurrency ---------------------------------------------------------------


async def test_concurrent_identical_registration_one_created_one_unchanged(
    registry_repo: SqlAlchemySourceRegistryRepository,
) -> None:
    await _ensure_publisher_registered(registry_repo)
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)

    async def _register() -> StructuredForecastOutcome:
        async with session_factory() as own_session:
            own_repo = SqlAlchemyStructuredForecastRepository(own_session)
            record = RecordStructuredForecast(own_repo)
            result = await record(_candidate("conc1"), registered_at=_ts(9))
            return result.outcome

    outcomes = await asyncio.gather(_register(), _register())

    assert sorted(o.value for o in outcomes) == sorted(
        [StructuredForecastOutcome.CREATED.value, StructuredForecastOutcome.UNCHANGED.value]
    )
    async with session_factory() as check_session:
        check_repo = SqlAlchemyStructuredForecastRepository(check_session)
        vintages = await check_repo.list_vintages_for_claim(f"{TEST_CLAIM_PREFIX}conc1")
        assert len(vintages) == 1


# --- No-write guarantee following a rejected candidate ------------------------


async def test_rejected_candidate_writes_nothing_real_postgres(
    forecast_repo: SqlAlchemyStructuredForecastRepository,
    registry_repo: SqlAlchemySourceRegistryRepository,
) -> None:
    await _ensure_publisher_registered(registry_repo)
    record = RecordStructuredForecast(forecast_repo)

    result = await record(
        _candidate("rejected1", target_key="NOT_A_REAL_TARGET"), registered_at=_ts(9)
    )

    assert result.outcome is StructuredForecastOutcome.REJECTED
    assert result.eligibility is ForecastCaptureEligibility.INSUFFICIENT_SPECIFICATION
    claim = await forecast_repo.get_claim(f"{TEST_CLAIM_PREFIX}rejected1")
    assert claim is None
