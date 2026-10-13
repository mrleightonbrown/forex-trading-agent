"""FX-62 Section 12.A/B: tests for `RecordSourceIdentityVintage` --
CREATED/REVISION_ADDED/UNCHANGED outcomes, PIT ordering, and the
determinism invariant defined for identity vintages (same `(source_
key, algorithm_version, evidence)` basis must never yield a different
COMPLETE derived identity payload -- `display_name`, `aliases`,
`authoritative_identifier`, AND `canonical_website`, per the FX-62H
correction below)."""

from datetime import UTC, datetime

import pytest

from forex_agent.application.use_cases.record_source_identity_vintage import (
    IntelligenceSourceKindMismatchError,
    OutOfOrderSourceIdentityError,
    RecordSourceIdentityVintage,
    SourceIdentityDeterminismError,
    SourceIdentityOutcome,
    SourceIdentityRecordResult,
)
from forex_agent.domain.intelligence_source_kind import IntelligenceSourceKind
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
    use_case: RecordSourceIdentityVintage,
    *,
    source_key: str = "FEDERAL_RESERVE",
    source_kind: IntelligenceSourceKind = IntelligenceSourceKind.ORGANIZATION,
    registered_at: UtcTimestamp | None = None,
    availability: UtcTimestamp | None = None,
    algorithm_version: str = "fx62_v1",
    display_name: str = "Federal Reserve",
    aliases: tuple[str, ...] = (),
    authoritative_identifier: str | None = None,
    canonical_website: str | None = None,
    evidence: SourceProvenanceEvidence | None = None,
    dry_run: bool = False,
) -> SourceIdentityRecordResult:
    return await use_case(
        source_key=source_key,
        source_kind=source_kind,
        registered_at=registered_at if registered_at is not None else _ts(9),
        availability=availability if availability is not None else _ts(9),
        algorithm_version=algorithm_version,
        display_name=display_name,
        aliases=aliases,
        authoritative_identifier=authoritative_identifier,
        canonical_website=canonical_website,
        evidence=evidence or _evidence(),
        dry_run=dry_run,
    )


@pytest.mark.asyncio
async def test_first_registration_is_created() -> None:
    repo = FakeSourceRegistryRepository()
    use_case = RecordSourceIdentityVintage(repo)

    result = await _record(use_case)

    assert result.outcome is SourceIdentityOutcome.CREATED
    assert result.identity_vintage.revision_sequence == 0
    assert len(await repo.list_sources()) == 1


@pytest.mark.asyncio
async def test_exact_repeat_is_unchanged_idempotent() -> None:
    repo = FakeSourceRegistryRepository()
    use_case = RecordSourceIdentityVintage(repo)
    await _record(use_case)

    result = await _record(use_case)

    assert result.outcome is SourceIdentityOutcome.UNCHANGED
    assert len(await repo.list_identity_vintages_for_source("FEDERAL_RESERVE")) == 1


@pytest.mark.asyncio
async def test_display_name_change_mints_a_revision() -> None:
    repo = FakeSourceRegistryRepository()
    use_case = RecordSourceIdentityVintage(repo)
    await _record(use_case, display_name="Federal Reserve", availability=_ts(9))

    result = await _record(
        use_case,
        display_name="Federal Reserve System",
        availability=_ts(10),
        evidence=_evidence("evidence B -- a genuine rename"),
    )

    assert result.outcome is SourceIdentityOutcome.REVISION_ADDED
    assert result.identity_vintage.revision_sequence == 1
    assert result.identity_vintage.display_name == "Federal Reserve System"


@pytest.mark.asyncio
async def test_out_of_order_availability_is_rejected() -> None:
    repo = FakeSourceRegistryRepository()
    use_case = RecordSourceIdentityVintage(repo)
    await _record(use_case, availability=_ts(10))

    with pytest.raises(OutOfOrderSourceIdentityError):
        await _record(use_case, availability=_ts(9), display_name="Different Name")


@pytest.mark.asyncio
async def test_equal_availability_is_permitted() -> None:
    repo = FakeSourceRegistryRepository()
    use_case = RecordSourceIdentityVintage(repo)
    await _record(use_case, availability=_ts(9), display_name="Federal Reserve")

    result = await _record(
        use_case,
        availability=_ts(9),
        display_name="Federal Reserve System",
        evidence=_evidence("evidence B"),
    )

    assert result.outcome is SourceIdentityOutcome.REVISION_ADDED


@pytest.mark.asyncio
async def test_kind_mismatch_is_rejected() -> None:
    repo = FakeSourceRegistryRepository()
    use_case = RecordSourceIdentityVintage(repo)
    await _record(use_case, source_kind=IntelligenceSourceKind.ORGANIZATION)

    with pytest.raises(IntelligenceSourceKindMismatchError):
        await _record(use_case, source_kind=IntelligenceSourceKind.TECHNICAL_FEED)


@pytest.mark.asyncio
async def test_same_basis_different_display_name_is_a_determinism_violation() -> None:
    """The SAME `(source_key, algorithm_version, evidence)` must never
    produce two different display names -- even when that exact basis
    is no longer the item's own latest row."""
    repo = FakeSourceRegistryRepository()
    use_case = RecordSourceIdentityVintage(repo)
    shared_evidence = _evidence("the exact same evidence, re-submitted")
    await _record(
        use_case,
        availability=_ts(9),
        display_name="Federal Reserve",
        evidence=shared_evidence,
    )
    # Move the latest row forward under different evidence.
    await _record(
        use_case,
        availability=_ts(10),
        display_name="Fed (temporary typo)",
        evidence=_evidence("a different, later evidence object"),
    )

    with pytest.raises(SourceIdentityDeterminismError):
        await _record(
            use_case,
            availability=_ts(11),
            display_name="A DIFFERENT name under the SAME original evidence",
            evidence=shared_evidence,
        )


@pytest.mark.asyncio
async def test_different_evidence_descriptions_are_not_compared_for_determinism() -> None:
    """Two genuinely different manual corrections (different evidence
    objects) are never compared against each other -- only identical
    evidence re-submitted under the identical algorithm_version is."""
    repo = FakeSourceRegistryRepository()
    use_case = RecordSourceIdentityVintage(repo)
    await _record(
        use_case,
        availability=_ts(9),
        display_name="Federal Reserve",
        evidence=_evidence("first manual review, 2026-01-01"),
    )

    result = await _record(
        use_case,
        availability=_ts(10),
        display_name="Federal Reserve System",
        evidence=_evidence("second manual review, 2026-01-02 -- genuine rename"),
    )

    assert result.outcome is SourceIdentityOutcome.REVISION_ADDED


@pytest.mark.asyncio
async def test_same_basis_different_aliases_is_a_determinism_violation() -> None:
    """FX-62H: the full-history check must compare `aliases`, not
    merely `display_name` -- same basis, same display_name, DIFFERENT
    aliases must still be caught."""
    repo = FakeSourceRegistryRepository()
    use_case = RecordSourceIdentityVintage(repo)
    shared_evidence = _evidence("the exact same evidence, re-submitted")
    await _record(
        use_case,
        availability=_ts(9),
        display_name="Federal Reserve",
        aliases=("Fed",),
        evidence=shared_evidence,
    )
    await _record(
        use_case,
        availability=_ts(10),
        display_name="Fed (temporary alias change)",
        aliases=("FOMC",),
        evidence=_evidence("a different, later evidence object"),
    )

    with pytest.raises(SourceIdentityDeterminismError):
        await _record(
            use_case,
            availability=_ts(11),
            display_name="Federal Reserve",
            aliases=("Federal Open Market Committee",),  # different aliases, same basis
            evidence=shared_evidence,
        )


@pytest.mark.asyncio
async def test_same_basis_different_authoritative_identifier_is_a_determinism_violation() -> None:
    """FX-62H: same basis, same display_name/aliases, DIFFERENT
    authoritative_identifier must still be caught."""
    repo = FakeSourceRegistryRepository()
    use_case = RecordSourceIdentityVintage(repo)
    shared_evidence = _evidence("the exact same evidence, re-submitted")
    await _record(
        use_case,
        availability=_ts(9),
        display_name="Federal Reserve",
        authoritative_identifier="LEI-AAA",
        evidence=shared_evidence,
    )
    await _record(
        use_case,
        availability=_ts(10),
        display_name="Fed (temporary identifier change)",
        authoritative_identifier="LEI-BBB",
        evidence=_evidence("a different, later evidence object"),
    )

    with pytest.raises(SourceIdentityDeterminismError):
        await _record(
            use_case,
            availability=_ts(11),
            display_name="Federal Reserve",
            authoritative_identifier="LEI-CCC",  # different identifier, same basis
            evidence=shared_evidence,
        )


@pytest.mark.asyncio
async def test_same_basis_different_canonical_website_is_a_determinism_violation() -> None:
    """FX-62H: same basis, same display_name/aliases/authoritative_
    identifier, DIFFERENT canonical_website must still be caught."""
    repo = FakeSourceRegistryRepository()
    use_case = RecordSourceIdentityVintage(repo)
    shared_evidence = _evidence("the exact same evidence, re-submitted")
    await _record(
        use_case,
        availability=_ts(9),
        display_name="Federal Reserve",
        canonical_website="https://www.federalreserve.gov",
        evidence=shared_evidence,
    )
    await _record(
        use_case,
        availability=_ts(10),
        display_name="Fed (temporary website change)",
        canonical_website="https://example.com/temp",
        evidence=_evidence("a different, later evidence object"),
    )

    with pytest.raises(SourceIdentityDeterminismError):
        await _record(
            use_case,
            availability=_ts(11),
            display_name="Federal Reserve",
            canonical_website="https://wrong.example.com",  # different website, same basis
            evidence=shared_evidence,
        )


@pytest.mark.asyncio
async def test_identical_historical_full_payload_is_not_a_violation() -> None:
    """Same basis, EXACT SAME complete payload (including aliases/
    authoritative_identifier/canonical_website) re-submitted after an
    intervening different-basis row must succeed, not raise."""
    repo = FakeSourceRegistryRepository()
    use_case = RecordSourceIdentityVintage(repo)
    shared_evidence = _evidence("the exact same evidence, re-submitted")
    await _record(
        use_case,
        availability=_ts(9),
        display_name="Federal Reserve",
        aliases=("Fed",),
        authoritative_identifier="LEI-AAA",
        canonical_website="https://www.federalreserve.gov",
        evidence=shared_evidence,
    )
    await _record(
        use_case,
        availability=_ts(10),
        display_name="Fed (temporary)",
        evidence=_evidence("a different, later evidence object"),
    )

    result = await _record(
        use_case,
        availability=_ts(11),
        display_name="Federal Reserve",
        aliases=("Fed",),
        authoritative_identifier="LEI-AAA",
        canonical_website="https://www.federalreserve.gov",
        evidence=shared_evidence,  # exact same basis, exact same complete payload
    )

    assert result.outcome is SourceIdentityOutcome.REVISION_ADDED
    assert result.identity_vintage.display_name == "Federal Reserve"
    assert result.identity_vintage.aliases == ("Fed",)


@pytest.mark.asyncio
async def test_new_evidence_supporting_changed_identity_is_not_a_violation() -> None:
    """A genuinely different evidence object under the same algorithm
    version is a different basis -- never compared, regardless of how
    many fields differ."""
    repo = FakeSourceRegistryRepository()
    use_case = RecordSourceIdentityVintage(repo)
    await _record(
        use_case,
        availability=_ts(9),
        display_name="Federal Reserve",
        aliases=("Fed",),
        authoritative_identifier="LEI-AAA",
        canonical_website="https://www.federalreserve.gov",
        evidence=_evidence("first manual review"),
    )

    result = await _record(
        use_case,
        availability=_ts(10),
        display_name="Federal Reserve System",
        aliases=("FOMC",),
        authoritative_identifier="LEI-BBB",
        canonical_website="https://example.com/new",
        evidence=_evidence("second manual review -- genuine comprehensive correction"),
    )

    assert result.outcome is SourceIdentityOutcome.REVISION_ADDED


@pytest.mark.asyncio
async def test_different_algorithm_version_is_not_a_violation() -> None:
    """A different `algorithm_version` under the same evidence is a
    different basis -- never compared against the prior algorithm
    version's own payload."""
    repo = FakeSourceRegistryRepository()
    use_case = RecordSourceIdentityVintage(repo)
    shared_evidence = _evidence("the exact same evidence, re-submitted")
    await _record(
        use_case,
        availability=_ts(9),
        algorithm_version="fx62_v1",
        display_name="Federal Reserve",
        evidence=shared_evidence,
    )

    result = await _record(
        use_case,
        availability=_ts(10),
        algorithm_version="fx62_v2",
        display_name="A completely different payload under v2",
        evidence=shared_evidence,
    )

    assert result.outcome is SourceIdentityOutcome.REVISION_ADDED


@pytest.mark.asyncio
async def test_full_history_v1_a_v2_b_v1_a_succeeds() -> None:
    """Section 8's own "an older pair can legitimately become latest
    again" worked example: v1(A) -> v2(B) -> v1(A) (A's own exact
    basis re-confirmed with its own exact original payload) must
    succeed."""
    repo = FakeSourceRegistryRepository()
    use_case = RecordSourceIdentityVintage(repo)
    evidence_v1 = _evidence("basis V1")
    evidence_v2 = _evidence("basis V2")
    await _record(
        use_case,
        availability=_ts(9),
        display_name="Payload A",
        aliases=("Alias A",),
        evidence=evidence_v1,
    )
    await _record(
        use_case,
        availability=_ts(10),
        display_name="Payload B",
        aliases=("Alias B",),
        evidence=evidence_v2,
    )

    result = await _record(
        use_case,
        availability=_ts(11),
        display_name="Payload A",
        aliases=("Alias A",),
        evidence=evidence_v1,  # same basis as the FIRST record -- same payload too
    )

    assert result.outcome is SourceIdentityOutcome.REVISION_ADDED
    assert result.identity_vintage.display_name == "Payload A"
    assert result.identity_vintage.aliases == ("Alias A",)


@pytest.mark.asyncio
async def test_full_history_v1_a_v2_b_v1_c_is_rejected() -> None:
    """The same worked example, but the third call's payload (C)
    genuinely differs from A under the exact same v1 basis -- this
    must be rejected as a determinism violation, even though v1(A) is
    no longer the item's own latest row at the time of the check."""
    repo = FakeSourceRegistryRepository()
    use_case = RecordSourceIdentityVintage(repo)
    evidence_v1 = _evidence("basis V1")
    evidence_v2 = _evidence("basis V2")
    await _record(
        use_case,
        availability=_ts(9),
        display_name="Payload A",
        aliases=("Alias A",),
        evidence=evidence_v1,
    )
    await _record(
        use_case,
        availability=_ts(10),
        display_name="Payload B",
        aliases=("Alias B",),
        evidence=evidence_v2,
    )

    with pytest.raises(SourceIdentityDeterminismError):
        await _record(
            use_case,
            availability=_ts(11),
            display_name="Payload A",
            aliases=("Alias C",),  # differs from A's own original aliases under the SAME v1 basis
            evidence=evidence_v1,
        )


@pytest.mark.asyncio
async def test_out_of_order_takes_precedence_over_determinism_conflict() -> None:
    """PIT ordering is checked FIRST, unconditionally -- an incoming
    vintage that is BOTH out-of-order AND would conflict on a
    determinism basis must raise `OutOfOrderSourceIdentityError`, never
    `SourceIdentityDeterminismError`."""
    repo = FakeSourceRegistryRepository()
    use_case = RecordSourceIdentityVintage(repo)
    shared_evidence = _evidence("the exact same evidence, re-submitted")
    await _record(
        use_case,
        availability=_ts(9),
        display_name="Federal Reserve",
        evidence=shared_evidence,
    )
    await _record(
        use_case,
        availability=_ts(20),
        display_name="Fed (later)",
        evidence=_evidence("later evidence"),
    )

    with pytest.raises(OutOfOrderSourceIdentityError):
        # Both out-of-order (availability=10 < latest's own 20) AND a
        # would-be determinism conflict (same shared_evidence basis,
        # different aliases from the first record) -- ordering wins.
        await _record(
            use_case,
            availability=_ts(10),
            display_name="Federal Reserve",
            aliases=("A conflicting alias",),
            evidence=shared_evidence,
        )


@pytest.mark.asyncio
async def test_dry_run_computes_but_never_writes() -> None:
    repo = FakeSourceRegistryRepository()
    use_case = RecordSourceIdentityVintage(repo)

    result = await _record(use_case, dry_run=True)

    assert result.outcome is SourceIdentityOutcome.CREATED
    assert await repo.get_source("FEDERAL_RESERVE") is None
    assert await repo.list_identity_vintages_for_source("FEDERAL_RESERVE") == ()


@pytest.mark.asyncio
async def test_registered_at_is_only_used_on_first_registration() -> None:
    repo = FakeSourceRegistryRepository()
    use_case = RecordSourceIdentityVintage(repo)
    await _record(use_case, registered_at=_ts(9), availability=_ts(9))

    await _record(
        use_case,
        registered_at=_ts(23),  # should be ignored -- source already registered
        availability=_ts(10),
        display_name="Renamed",
        evidence=_evidence("a later evidence"),
    )

    source = await repo.get_source("FEDERAL_RESERVE")
    assert source is not None
    assert source.registered_at == _ts(9)
