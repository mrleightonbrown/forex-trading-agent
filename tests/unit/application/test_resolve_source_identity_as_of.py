"""FX-62 Section 12.B: tests for `ResolveSourceIdentityAsOf` --
KNOWN/NOT_KNOWN, including "an identity discovered today must not
automatically appear in historical snapshots from last month"."""

from datetime import UTC, datetime

import pytest

from forex_agent.application.use_cases.record_source_identity_vintage import (
    RecordSourceIdentityVintage,
)
from forex_agent.application.use_cases.resolve_source_identity_as_of import (
    ResolveSourceIdentityAsOf,
    SourceIdentityResolution,
)
from forex_agent.domain.intelligence_source_kind import IntelligenceSourceKind
from forex_agent.domain.source_evidence_kind import SourceEvidenceKind
from forex_agent.domain.source_provenance_evidence import SourceProvenanceEvidence
from forex_agent.domain.timestamps import UtcTimestamp
from tests.fakes.source_registry_repository import FakeSourceRegistryRepository


def _ts(hour: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, hour, tzinfo=UTC))


def _evidence() -> SourceProvenanceEvidence:
    return SourceProvenanceEvidence(
        evidence_kind=SourceEvidenceKind.ADAPTER_CONFIGURATION, description="test"
    )


@pytest.mark.asyncio
async def test_not_known_before_registration() -> None:
    repo = FakeSourceRegistryRepository()
    resolve = ResolveSourceIdentityAsOf(repo)

    result = await resolve("FEDERAL_RESERVE", _ts(9))

    assert result.resolution is SourceIdentityResolution.NOT_KNOWN
    assert result.identity_vintage is None


@pytest.mark.asyncio
async def test_known_at_and_after_registration() -> None:
    repo = FakeSourceRegistryRepository()
    record = RecordSourceIdentityVintage(repo)
    await record(
        source_key="FEDERAL_RESERVE",
        source_kind=IntelligenceSourceKind.ORGANIZATION,
        registered_at=_ts(10),
        availability=_ts(10),
        algorithm_version="fx62_v1",
        display_name="Federal Reserve",
        aliases=(),
        authoritative_identifier=None,
        canonical_website=None,
        evidence=_evidence(),
    )
    resolve = ResolveSourceIdentityAsOf(repo)

    at_registration = await resolve("FEDERAL_RESERVE", _ts(10))
    after_registration = await resolve("FEDERAL_RESERVE", _ts(11))

    assert at_registration.resolution is SourceIdentityResolution.KNOWN
    assert after_registration.resolution is SourceIdentityResolution.KNOWN


@pytest.mark.asyncio
async def test_not_known_before_registration_even_though_known_later() -> None:
    """Section 6: an identity discovered today must not automatically
    appear in historical snapshots from before it was registered."""
    repo = FakeSourceRegistryRepository()
    record = RecordSourceIdentityVintage(repo)
    await record(
        source_key="FEDERAL_RESERVE",
        source_kind=IntelligenceSourceKind.ORGANIZATION,
        registered_at=_ts(10),
        availability=_ts(10),
        algorithm_version="fx62_v1",
        display_name="Federal Reserve",
        aliases=(),
        authoritative_identifier=None,
        canonical_website=None,
        evidence=_evidence(),
    )
    resolve = ResolveSourceIdentityAsOf(repo)

    before_registration = await resolve("FEDERAL_RESERVE", _ts(9))

    assert before_registration.resolution is SourceIdentityResolution.NOT_KNOWN
    assert before_registration.identity_vintage is None
