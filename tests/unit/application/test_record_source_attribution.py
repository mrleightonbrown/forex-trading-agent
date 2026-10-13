"""FX-62 Section 12.A/B/C: tests for `RecordSourceAttribution` --
CREATED/REVISION_ADDED/UNCHANGED outcomes, PIT ordering, per-role
independence (PUBLISHER vs ORIGINATING_CLAIMANT never interfere with
each other), and the FX-59H-mirrored determinism invariant over
`(news_item_key, role, evidence_basis_revision_sequence, algorithm_
version)`."""

from datetime import UTC, datetime

import pytest

from forex_agent.application.use_cases.record_source_attribution import (
    OutOfOrderSourceAttributionError,
    RecordSourceAttribution,
    SourceAttributionDeterminismError,
    SourceAttributionOutcome,
    SourceAttributionRecordResult,
)
from forex_agent.domain.source_attribution_role import SourceAttributionRole
from forex_agent.domain.source_attribution_status import SourceAttributionStatus
from forex_agent.domain.source_evidence_kind import SourceEvidenceKind
from forex_agent.domain.source_provenance_evidence import SourceProvenanceEvidence
from forex_agent.domain.timestamps import UtcTimestamp
from tests.fakes.source_registry_repository import FakeSourceRegistryRepository


def _ts(hour: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, hour, tzinfo=UTC))


def _evidence(description: str = "evidence A") -> SourceProvenanceEvidence:
    return SourceProvenanceEvidence(
        evidence_kind=SourceEvidenceKind.ADAPTER_CONFIGURATION, description=description
    )


async def _record(
    use_case: RecordSourceAttribution,
    *,
    news_item_key: str = "ITEM-1",
    role: SourceAttributionRole = SourceAttributionRole.PUBLISHER,
    availability: UtcTimestamp | None = None,
    algorithm_version: str = "fx62_v1",
    status: SourceAttributionStatus = SourceAttributionStatus.CONFIRMED,
    attributed_source_key: str | None = "FEDERAL_RESERVE",
    evidence_basis_revision_sequence: int = 0,
    evidence: SourceProvenanceEvidence | None = None,
) -> SourceAttributionRecordResult:
    return await use_case(
        news_item_key=news_item_key,
        role=role,
        availability=availability if availability is not None else _ts(9),
        algorithm_version=algorithm_version,
        status=status,
        attributed_source_key=attributed_source_key,
        evidence_basis_revision_sequence=evidence_basis_revision_sequence,
        evidence=evidence or _evidence(),
    )


@pytest.mark.asyncio
async def test_first_attribution_is_created() -> None:
    repo = FakeSourceRegistryRepository()
    use_case = RecordSourceAttribution(repo)

    result = await _record(use_case)

    assert result.outcome is SourceAttributionOutcome.CREATED
    assert result.attribution_vintage.revision_sequence == 0


@pytest.mark.asyncio
async def test_exact_repeat_is_unchanged_idempotent() -> None:
    repo = FakeSourceRegistryRepository()
    use_case = RecordSourceAttribution(repo)
    await _record(use_case)

    result = await _record(use_case)

    assert result.outcome is SourceAttributionOutcome.UNCHANGED
    assert len(await repo.list_attribution_vintages("ITEM-1", SourceAttributionRole.PUBLISHER)) == 1


@pytest.mark.asyncio
async def test_new_basis_revision_mints_a_new_attribution_revision() -> None:
    repo = FakeSourceRegistryRepository()
    use_case = RecordSourceAttribution(repo)
    await _record(use_case, evidence_basis_revision_sequence=0, availability=_ts(9))

    result = await _record(
        use_case,
        evidence_basis_revision_sequence=1,
        availability=_ts(10),
        evidence=_evidence("re-evaluated against revision 1"),
    )

    assert result.outcome is SourceAttributionOutcome.REVISION_ADDED
    assert result.attribution_vintage.revision_sequence == 1


@pytest.mark.asyncio
async def test_out_of_order_availability_is_rejected() -> None:
    repo = FakeSourceRegistryRepository()
    use_case = RecordSourceAttribution(repo)
    await _record(use_case, availability=_ts(10))

    with pytest.raises(OutOfOrderSourceAttributionError):
        await _record(use_case, availability=_ts(9), evidence_basis_revision_sequence=1)


@pytest.mark.asyncio
async def test_publisher_and_claimant_roles_have_independent_revision_histories() -> None:
    """FX-62 Section 4.3: a PUBLISHER correction never touches
    ORIGINATING_CLAIMANT's own independent revision history."""
    repo = FakeSourceRegistryRepository()
    use_case = RecordSourceAttribution(repo)
    await _record(
        use_case,
        role=SourceAttributionRole.PUBLISHER,
        attributed_source_key="BANK_OF_ENGLAND",
        availability=_ts(9),
    )
    await _record(
        use_case,
        role=SourceAttributionRole.ORIGINATING_CLAIMANT,
        status=SourceAttributionStatus.UNRESOLVED,
        attributed_source_key=None,
        availability=_ts(9),
    )

    # Correcting PUBLISHER must not disturb ORIGINATING_CLAIMANT's own history.
    await _record(
        use_case,
        role=SourceAttributionRole.PUBLISHER,
        attributed_source_key="HM_TREASURY",
        availability=_ts(10),
        evidence=_evidence("publisher correction"),
    )

    publisher_history = await repo.list_attribution_vintages(
        "ITEM-1", SourceAttributionRole.PUBLISHER
    )
    claimant_history = await repo.list_attribution_vintages(
        "ITEM-1", SourceAttributionRole.ORIGINATING_CLAIMANT
    )
    assert len(publisher_history) == 2
    assert len(claimant_history) == 1
    assert claimant_history[0].status is SourceAttributionStatus.UNRESOLVED


@pytest.mark.asyncio
async def test_same_basis_different_attribution_is_a_determinism_violation() -> None:
    repo = FakeSourceRegistryRepository()
    use_case = RecordSourceAttribution(repo)
    await _record(
        use_case,
        evidence_basis_revision_sequence=0,
        attributed_source_key="BANK_OF_ENGLAND",
        availability=_ts(9),
    )
    # Move latest forward under a different basis.
    await _record(
        use_case,
        evidence_basis_revision_sequence=1,
        attributed_source_key="HM_TREASURY",
        availability=_ts(10),
        evidence=_evidence("later basis"),
    )

    with pytest.raises(SourceAttributionDeterminismError):
        await _record(
            use_case,
            evidence_basis_revision_sequence=0,
            attributed_source_key="A_DIFFERENT_ORG",
            availability=_ts(11),
        )


@pytest.mark.asyncio
async def test_mentioned_institution_requires_explicit_evidence_never_assumed() -> None:
    """FX-62 Section 5's own explicit prohibition: never assume every
    institution mentioned is the publisher. This use case has no
    mechanism to infer attribution from mentions at all -- the only
    way an attribution exists is an explicit caller-supplied `status`/
    `attributed_source_key`, confirmed here by recording an explicit
    UNRESOLVED claimant even when a PUBLISHER is confirmed."""
    repo = FakeSourceRegistryRepository()
    use_case = RecordSourceAttribution(repo)
    await _record(
        use_case, role=SourceAttributionRole.PUBLISHER, attributed_source_key="BANK_OF_ENGLAND"
    )

    result = await _record(
        use_case,
        role=SourceAttributionRole.ORIGINATING_CLAIMANT,
        status=SourceAttributionStatus.UNRESOLVED,
        attributed_source_key=None,
    )

    assert result.attribution_vintage.status is SourceAttributionStatus.UNRESOLVED
    assert result.attribution_vintage.attributed_source_key is None


@pytest.mark.asyncio
async def test_quoted_actor_is_never_automatically_the_claimant() -> None:
    repo = FakeSourceRegistryRepository()
    use_case = RecordSourceAttribution(repo)
    await _record(
        use_case, role=SourceAttributionRole.QUOTED_ACTOR, attributed_source_key="SOME_PERSON"
    )
    result = await _record(
        use_case,
        role=SourceAttributionRole.ORIGINATING_CLAIMANT,
        status=SourceAttributionStatus.UNRESOLVED,
        attributed_source_key=None,
    )

    assert result.attribution_vintage.status is SourceAttributionStatus.UNRESOLVED
