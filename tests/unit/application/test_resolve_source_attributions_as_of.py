"""FX-62 Section 12.B/C: tests for `ResolveSourceAttributionsAsOf` --
deterministic ordering, confirmed/unresolved separation, and multi-
role resolution for one NewsItem."""

from datetime import UTC, datetime

import pytest

from forex_agent.application.use_cases.record_source_attribution import RecordSourceAttribution
from forex_agent.application.use_cases.resolve_source_attributions_as_of import (
    ResolveSourceAttributionsAsOf,
)
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
async def test_empty_when_nothing_recorded() -> None:
    repo = FakeSourceRegistryRepository()
    resolve = ResolveSourceAttributionsAsOf(repo)

    result = await resolve("ITEM-1", _ts(10))

    assert result.attributions == ()
    assert result.confirmed == ()
    assert result.unresolved == ()


@pytest.mark.asyncio
async def test_multiple_roles_resolved_and_deterministically_ordered() -> None:
    repo = FakeSourceRegistryRepository()
    record = RecordSourceAttribution(repo)
    await record(
        news_item_key="ITEM-1",
        role=SourceAttributionRole.QUOTED_ACTOR,
        availability=_ts(9),
        algorithm_version="fx62_v1",
        status=SourceAttributionStatus.CONFIRMED,
        attributed_source_key="SOME_PERSON",
        evidence_basis_revision_sequence=0,
        evidence=_evidence(),
    )
    await record(
        news_item_key="ITEM-1",
        role=SourceAttributionRole.PUBLISHER,
        availability=_ts(9),
        algorithm_version="fx62_v1",
        status=SourceAttributionStatus.CONFIRMED,
        attributed_source_key="BANK_OF_ENGLAND",
        evidence_basis_revision_sequence=0,
        evidence=_evidence(),
    )
    await record(
        news_item_key="ITEM-1",
        role=SourceAttributionRole.ORIGINATING_CLAIMANT,
        availability=_ts(9),
        algorithm_version="fx62_v1",
        status=SourceAttributionStatus.UNRESOLVED,
        attributed_source_key=None,
        evidence_basis_revision_sequence=0,
        evidence=_evidence(),
    )
    resolve = ResolveSourceAttributionsAsOf(repo)

    result = await resolve("ITEM-1", _ts(10))

    assert len(result.attributions) == 3
    # Deterministically ordered by role.value, never insertion order.
    assert [a.role.value for a in result.attributions] == sorted(
        a.role.value for a in result.attributions
    )
    assert len(result.confirmed) == 2
    assert len(result.unresolved) == 1
    assert result.unresolved[0].role is SourceAttributionRole.ORIGINATING_CLAIMANT


@pytest.mark.asyncio
async def test_role_with_no_attribution_is_simply_absent() -> None:
    repo = FakeSourceRegistryRepository()
    record = RecordSourceAttribution(repo)
    await record(
        news_item_key="ITEM-1",
        role=SourceAttributionRole.PUBLISHER,
        availability=_ts(9),
        algorithm_version="fx62_v1",
        status=SourceAttributionStatus.CONFIRMED,
        attributed_source_key="BANK_OF_ENGLAND",
        evidence_basis_revision_sequence=0,
        evidence=_evidence(),
    )
    resolve = ResolveSourceAttributionsAsOf(repo)

    result = await resolve("ITEM-1", _ts(10))

    assert len(result.attributions) == 1
    assert result.attributions[0].role is SourceAttributionRole.PUBLISHER
