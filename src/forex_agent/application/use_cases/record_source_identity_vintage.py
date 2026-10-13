"""FX-62: append-only recording of FTA's own knowledge about ONE
`IntelligenceSource` identity -- following `RecordNewsSemanticAnnotation`
(FX-59H)'s own established shape exactly: compare the latest stored
state, and only append a new revision when the incoming payload
genuinely differs.

**Precedence, mirroring FX-56H.1/FX-59H's own corrected lesson ("check
ordering FIRST, unconditionally, THEN check identity")**: PIT ordering
is checked before anything else. An incoming vintage whose `availability`
is EARLIER than the source's own latest recorded vintage always raises
`OutOfOrderSourceIdentityError` -- an earlier `availability` is itself
an assertion about when FTA knew this, and that assertion must be
rejected regardless of content. Equal `availability` is explicitly
permitted.

**Determinism (FX-62 Section 8), defined precisely for identity
vintages**: unlike FX-59's semantic classification (a pure function of
a FIXED `NewsItemVintage` basis, where the SAME basis MUST always
yield the SAME output), a source's own real-world identity facts
(display name, aliases) can LEGITIMATELY change over time for reasons
entirely independent of any fixed "basis" -- an organization can
genuinely rename itself. There is therefore no sound analog of "the
same basis always yields the same output" UNLESS the historical basis
is pinned EXACTLY, including which evidence FTA actually read. This
use case treats `(source_key, algorithm_version, evidence)` -- the
WHOLE `SourceProvenanceEvidence` value, not merely its `evidence_kind`
-- as that exact historical basis, mirroring FX-59's own `(basis_news_
item_revision_sequence, algorithm_version)` pair: re-submitting the
EXACT SAME evidence under the EXACT SAME policy version must always
extract the SAME `(display_name, aliases, authoritative_identifier,
canonical_website)` -- a different evidence object (even of the same
`evidence_kind`, e.g. two genuinely different manual reviews) is a
genuinely different basis and is never compared against this
invariant, exactly as a different `basis_news_item_revision_sequence`
in FX-59 is never compared. Checked against the source's ENTIRE stored
identity-vintage history, not merely whichever row is currently
latest -- an older `(algorithm_version, evidence)` pair can legitimately
become "latest" again later (e.g. a corrected alias is reverted), and a
stale, different payload for that exact same pair must still be
caught even though it is no longer the current row.

**FX-62H correction: the full-history check above originally compared
ONLY `display_name`, silently allowing a historical conflict in
`aliases`, `authoritative_identifier`, or `canonical_website` under
the exact same `(source_key, algorithm_version, evidence)` basis to
pass undetected.** The comparison is now the COMPLETE derived payload
`(display_name, aliases, authoritative_identifier, canonical_website)`
-- see `IdentityPayload` below -- matching what this docstring already
described as the invariant. The determinism key itself (`(source_key,
algorithm_version, evidence)`) is unchanged; this was a comparison-
completeness defect, not a key-shape defect."""

from dataclasses import dataclass
from enum import Enum

from forex_agent.application.ports.source_registry_repository import SourceRegistryRepository
from forex_agent.domain.intelligence_source import IntelligenceSource
from forex_agent.domain.intelligence_source_kind import IntelligenceSourceKind
from forex_agent.domain.source_identity_vintage import SourceIdentityVintage
from forex_agent.domain.source_provenance_evidence import SourceProvenanceEvidence
from forex_agent.domain.timestamps import UtcTimestamp


class SourceIdentityOutcome(Enum):
    """What `RecordSourceIdentityVintage` actually did (mirrors
    `NewsSemanticAnnotationOutcome`)."""

    CREATED = "CREATED"
    REVISION_ADDED = "REVISION_ADDED"
    UNCHANGED = "UNCHANGED"


@dataclass(frozen=True, slots=True)
class SourceIdentityRecordResult:
    source_key: str
    outcome: SourceIdentityOutcome
    identity_vintage: SourceIdentityVintage
    """The relevant vintage after this call: the newly-written one for
    `CREATED`/`REVISION_ADDED`, or the EXISTING one for `UNCHANGED`."""


class IntelligenceSourceKindMismatchError(Exception):
    """Raised when `source_kind` disagrees with an already-registered
    `IntelligenceSource`'s own `source_kind` -- Section 4.1's own "a
    durable source key must not be reassigned to a different actor"
    invariant."""

    def __init__(self, source_key: str, existing_kind: IntelligenceSourceKind) -> None:
        self.source_key = source_key
        self.existing_kind = existing_kind
        super().__init__(
            f"source_key={source_key!r} is already registered as {existing_kind.value!r} -- "
            "a durable source key must never be reassigned to a different actor"
        )


class OutOfOrderSourceIdentityError(Exception):
    """Raised when an incoming identity vintage claims an `availability`
    earlier than the source's own latest recorded vintage."""

    def __init__(
        self,
        source_key: str,
        latest_availability: UtcTimestamp,
        incoming_availability: UtcTimestamp,
    ) -> None:
        self.source_key = source_key
        self.latest_availability = latest_availability
        self.incoming_availability = incoming_availability
        super().__init__(
            f"identity vintage for source_key={source_key!r} claims availability="
            f"{incoming_availability.value.isoformat()}, earlier than the latest recorded "
            f"vintage's own availability={latest_availability.value.isoformat()} -- refusing "
            "to append a backdated identity assertion"
        )


IdentityPayload = tuple[str, tuple[str, ...], str | None, str | None]
"""The COMPLETE derived identity payload this use case extracts from
evidence -- `(display_name, aliases, authoritative_identifier,
canonical_website)` -- in that fixed field order, used wherever two
payloads must be compared for determinism."""


class SourceIdentityDeterminismError(Exception):
    """Raised when the SAME `(source_key, algorithm_version, evidence)`
    historical basis produces a DIFFERENT derived identity payload --
    `(display_name, aliases, authoritative_identifier, canonical_
    website)`, the COMPLETE set of fields this use case derives from
    evidence, not merely `display_name` -- than SOME ALREADY-STORED
    vintage for that exact basis. See the module docstring for why
    `evidence` (not merely `evidence_kind`) is part of this basis."""

    def __init__(
        self,
        source_key: str,
        algorithm_version: str,
        evidence: SourceProvenanceEvidence,
        existing_payload: IdentityPayload,
        incoming_payload: IdentityPayload,
    ) -> None:
        self.source_key = source_key
        self.algorithm_version = algorithm_version
        self.evidence = evidence
        self.existing_payload = existing_payload
        self.incoming_payload = incoming_payload
        super().__init__(
            f"source_key={source_key!r}, algorithm_version={algorithm_version!r}, evidence="
            f"{evidence!r} already produced a DIFFERENT identity payload: existing "
            "(display_name, aliases, authoritative_identifier, canonical_website)="
            f"{existing_payload!r}, incoming={incoming_payload!r} -- the SAME evidence read "
            "under the SAME policy version must never produce two different identity payloads"
        )


class RecordSourceIdentityVintage:
    """FX-62's own append-only source-identity-recording use case --
    see the module docstring. Handles BOTH the first-ever registration
    of a durable `IntelligenceSource` (atomically, with its own first
    vintage -- mirroring `RecordNewsObservation`'s own FX-56H atomic
    first-registration pattern) and every subsequent revision,
    transparently."""

    def __init__(self, repository: SourceRegistryRepository) -> None:
        self._repository = repository

    async def __call__(
        self,
        source_key: str,
        source_kind: IntelligenceSourceKind,
        registered_at: UtcTimestamp,
        availability: UtcTimestamp,
        algorithm_version: str,
        display_name: str,
        aliases: tuple[str, ...],
        authoritative_identifier: str | None,
        canonical_website: str | None,
        evidence: SourceProvenanceEvidence,
        *,
        correction_reason: str | None = None,
        dry_run: bool = False,
    ) -> SourceIdentityRecordResult:
        """`registered_at` is used ONLY when `source_key` has never
        been registered before -- it is the durable `IntelligenceSource.
        registered_at`, never revised afterward. `dry_run=True`
        computes and returns the EXACT SAME outcome a real call would,
        using the EXACT SAME decision logic below, but never writes."""
        existing_source = await self._repository.get_source(source_key)
        if existing_source is not None and existing_source.source_kind is not source_kind:
            raise IntelligenceSourceKindMismatchError(source_key, existing_source.source_kind)

        latest = (
            await self._repository.latest_identity_vintage_for_source(source_key)
            if existing_source is not None
            else None
        )

        if latest is not None and availability.value < latest.availability.value:
            raise OutOfOrderSourceIdentityError(source_key, latest.availability, availability)

        incoming_payload: IdentityPayload = (
            display_name,
            aliases,
            authoritative_identifier,
            canonical_website,
        )
        if existing_source is not None:
            history = await self._repository.list_identity_vintages_for_source(source_key)
            for historical in history:
                historical_payload: IdentityPayload = (
                    historical.display_name,
                    historical.aliases,
                    historical.authoritative_identifier,
                    historical.canonical_website,
                )
                if (
                    historical.algorithm_version == algorithm_version
                    and historical.evidence == evidence
                    and historical_payload != incoming_payload
                ):
                    raise SourceIdentityDeterminismError(
                        source_key,
                        algorithm_version,
                        evidence,
                        historical_payload,
                        incoming_payload,
                    )

        if existing_source is None:
            source = IntelligenceSource(
                source_key=source_key, source_kind=source_kind, registered_at=registered_at
            )
            created_vintage = SourceIdentityVintage(
                source_key=source_key,
                revision_sequence=0,
                availability=availability,
                algorithm_version=algorithm_version,
                display_name=display_name,
                aliases=aliases,
                authoritative_identifier=authoritative_identifier,
                canonical_website=canonical_website,
                evidence=evidence,
                correction_reason=correction_reason,
            )
            if dry_run:
                return SourceIdentityRecordResult(
                    source_key, SourceIdentityOutcome.CREATED, created_vintage
                )
            registration = await self._repository.register_source_with_first_identity_vintage(
                source, created_vintage
            )
            outcome = (
                SourceIdentityOutcome.CREATED
                if registration.created
                else SourceIdentityOutcome.UNCHANGED
            )
            return SourceIdentityRecordResult(source_key, outcome, created_vintage)

        assert latest is not None  # an existing source always has >=1 vintage (atomic creation)

        latest_payload: IdentityPayload = (
            latest.display_name,
            latest.aliases,
            latest.authoritative_identifier,
            latest.canonical_website,
        )
        if (
            latest.algorithm_version == algorithm_version
            and latest.evidence == evidence
            and latest_payload == incoming_payload
        ):
            # `evidence` is part of this comparison (mirroring `latest.
            # algorithm_version == algorithm_version`): a DIFFERENT
            # evidence object re-confirming the SAME output still mints
            # a new revision, for full provenance-audit fidelity --
            # "this same display name was ALSO confirmed by a second,
            # independent source" is a genuine historical fact worth
            # recording, not silently dropped as a no-op.
            return SourceIdentityRecordResult(source_key, SourceIdentityOutcome.UNCHANGED, latest)

        revised_vintage = SourceIdentityVintage(
            source_key=source_key,
            revision_sequence=latest.revision_sequence + 1,
            availability=availability,
            algorithm_version=algorithm_version,
            display_name=display_name,
            aliases=aliases,
            authoritative_identifier=authoritative_identifier,
            canonical_website=canonical_website,
            evidence=evidence,
            correction_reason=correction_reason,
        )
        if dry_run:
            return SourceIdentityRecordResult(
                source_key, SourceIdentityOutcome.REVISION_ADDED, revised_vintage
            )
        write_result = await self._repository.add_identity_vintage(revised_vintage)
        outcome = (
            SourceIdentityOutcome.REVISION_ADDED
            if write_result.inserted
            else SourceIdentityOutcome.UNCHANGED
        )
        return SourceIdentityRecordResult(source_key, outcome, revised_vintage)
