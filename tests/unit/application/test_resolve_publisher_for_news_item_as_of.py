"""FX-62 Section 12.B/C: tests for `ResolvePublisherForNewsItemAsOf`
-- CONFIRMED/UNRESOLVED/NOT_RECORDED, and the explicit requirement
that this resolver NEVER substitutes the technical ingestion feed for
an unknown publishing actor."""

from datetime import UTC, datetime

import pytest

from forex_agent.application.use_cases.record_source_attribution import RecordSourceAttribution
from forex_agent.application.use_cases.record_source_identity_vintage import (
    RecordSourceIdentityVintage,
)
from forex_agent.application.use_cases.resolve_publisher_for_news_item_as_of import (
    PublisherResolutionStatus,
    ResolvePublisherForNewsItemAsOf,
)
from forex_agent.domain.intelligence_source_kind import IntelligenceSourceKind
from forex_agent.domain.source_attribution_role import SourceAttributionRole
from forex_agent.domain.source_attribution_status import SourceAttributionStatus
from forex_agent.domain.source_evidence_kind import SourceEvidenceKind
from forex_agent.domain.source_provenance_evidence import SourceProvenanceEvidence
from forex_agent.domain.timestamps import UtcTimestamp
from tests.fakes.source_registry_repository import FakeSourceRegistryRepository


def _ts(hour: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, hour, tzinfo=UTC))


def _evidence(description: str = "test") -> SourceProvenanceEvidence:
    return SourceProvenanceEvidence(
        evidence_kind=SourceEvidenceKind.ADAPTER_CONFIGURATION, description=description
    )


@pytest.mark.asyncio
async def test_not_recorded_when_nothing_exists() -> None:
    repo = FakeSourceRegistryRepository()
    resolve = ResolvePublisherForNewsItemAsOf(repo)

    result = await resolve("ITEM-1", _ts(10))

    assert result.status is PublisherResolutionStatus.NOT_RECORDED
    assert result.publisher is None
    assert result.attribution_vintage is None


@pytest.mark.asyncio
async def test_unresolved_when_explicitly_recorded_as_unresolved() -> None:
    repo = FakeSourceRegistryRepository()
    record_attribution = RecordSourceAttribution(repo)
    await record_attribution(
        news_item_key="ITEM-1",
        role=SourceAttributionRole.PUBLISHER,
        availability=_ts(9),
        algorithm_version="fx62_v1",
        status=SourceAttributionStatus.UNRESOLVED,
        attributed_source_key=None,
        evidence_basis_revision_sequence=0,
        evidence=_evidence(),
    )
    resolve = ResolvePublisherForNewsItemAsOf(repo)

    result = await resolve("ITEM-1", _ts(10))

    assert result.status is PublisherResolutionStatus.UNRESOLVED
    assert result.publisher is None
    assert result.attribution_vintage is not None


@pytest.mark.asyncio
async def test_confirmed_resolves_the_full_organization_identity() -> None:
    repo = FakeSourceRegistryRepository()
    record_identity = RecordSourceIdentityVintage(repo)
    await record_identity(
        source_key="BANK_OF_ENGLAND",
        source_kind=IntelligenceSourceKind.ORGANIZATION,
        registered_at=_ts(8),
        availability=_ts(8),
        algorithm_version="fx62_v1",
        display_name="Bank of England",
        aliases=(),
        authoritative_identifier=None,
        canonical_website=None,
        evidence=_evidence(),
    )
    record_attribution = RecordSourceAttribution(repo)
    await record_attribution(
        news_item_key="ITEM-1",
        role=SourceAttributionRole.PUBLISHER,
        availability=_ts(9),
        algorithm_version="fx62_v1",
        status=SourceAttributionStatus.CONFIRMED,
        attributed_source_key="BANK_OF_ENGLAND",
        evidence_basis_revision_sequence=0,
        evidence=_evidence(),
    )
    resolve = ResolvePublisherForNewsItemAsOf(repo)

    result = await resolve("ITEM-1", _ts(10))

    assert result.status is PublisherResolutionStatus.CONFIRMED
    assert result.publisher is not None
    assert result.publisher.source_key == "BANK_OF_ENGLAND"
    assert result.publisher_identity_vintage is not None
    assert result.publisher_identity_vintage.display_name == "Bank of England"


@pytest.mark.asyncio
async def test_never_falls_back_to_the_technical_feed() -> None:
    """Section 7's own explicit prohibition: the publisher resolver
    must not silently substitute the technical feed when the
    publishing actor is unknown."""
    repo = FakeSourceRegistryRepository()
    record_identity = RecordSourceIdentityVintage(repo)
    # The TECHNICAL_FEED identity exists, but no PUBLISHER attribution
    # has ever been recorded for this item.
    await record_identity(
        source_key="BOE",
        source_kind=IntelligenceSourceKind.TECHNICAL_FEED,
        registered_at=_ts(8),
        availability=_ts(8),
        algorithm_version="fx62_v1",
        display_name="Bank of England (feed)",
        aliases=(),
        authoritative_identifier=None,
        canonical_website=None,
        evidence=_evidence(),
    )
    resolve = ResolvePublisherForNewsItemAsOf(repo)

    result = await resolve("ITEM-1", _ts(10))

    assert result.status is PublisherResolutionStatus.NOT_RECORDED
    assert result.publisher is None


@pytest.mark.asyncio
async def test_pit_safe_publisher_resolution_before_attribution_recorded() -> None:
    repo = FakeSourceRegistryRepository()
    record_attribution = RecordSourceAttribution(repo)
    await record_attribution(
        news_item_key="ITEM-1",
        role=SourceAttributionRole.PUBLISHER,
        availability=_ts(10),
        algorithm_version="fx62_v1",
        status=SourceAttributionStatus.CONFIRMED,
        attributed_source_key="BANK_OF_ENGLAND",
        evidence_basis_revision_sequence=0,
        evidence=_evidence(),
    )
    resolve = ResolvePublisherForNewsItemAsOf(repo)

    before = await resolve("ITEM-1", _ts(9))
    at_and_after = await resolve("ITEM-1", _ts(10))

    assert before.status is PublisherResolutionStatus.NOT_RECORDED
    assert at_and_after.status is PublisherResolutionStatus.CONFIRMED
