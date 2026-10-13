"""FX-62: append-only recording of ONE `(news_item_key, role)`
attribution -- following `RecordNewsSemanticAnnotation` (FX-59H)'s own
established shape exactly, scoped per role so a PUBLISHER correction
never touches ORIGINATING_CLAIMANT's own independent revision history
(Section 4.3).

**Precedence, mirroring FX-56H.1/FX-59H's own corrected lesson**: PIT
ordering is checked FIRST, unconditionally -- an incoming attribution
whose `availability` is earlier than this `(news_item_key, role)`
pair's own latest recorded vintage always raises `OutOfOrderSource
AttributionError`, regardless of content.

**Determinism (FX-62 Section 8)**: `evidence_basis_revision_sequence`
pins the exact `NewsItemVintage` FTA evaluated (an FX-59-style fixed
basis), but -- UNLIKE FX-59's own pure-function classification --
WHO FTA believes the publisher/claimant to be is not solely a
function of that vintage's own text: Section 9's own worked example
(T2 confirms publisher A; T3 discovers A was WRONG and corrects to B,
having read no new vintage at all, `evidence_basis_revision_sequence`
UNCHANGED) is an explicitly anticipated, legitimate scenario, not a
bug. The determinism key therefore ALSO includes the full `evidence`
object, exactly mirroring `RecordSourceIdentityVintage`'s own
identical reasoning: `(news_item_key, role, evidence_basis_revision_
sequence, algorithm_version, evidence)` -- the SAME evidence
re-submitted under the SAME basis and policy must always yield the
SAME `(status, attributed_source_key)`; a genuinely DIFFERENT
evidence object (e.g. T3's own correction evidence, distinct from
T2's own confirming evidence) is a genuinely different historical
basis and is never compared against it. Checked against this `(news_
item_key, role)` pair's ENTIRE stored history, not merely whichever
row is currently latest -- mirroring FX-59H's own full-history
rationale exactly."""

from dataclasses import dataclass
from enum import Enum

from forex_agent.application.ports.source_registry_repository import SourceRegistryRepository
from forex_agent.domain.source_attribution_role import SourceAttributionRole
from forex_agent.domain.source_attribution_status import SourceAttributionStatus
from forex_agent.domain.source_attribution_vintage import SourceAttributionVintage
from forex_agent.domain.source_provenance_evidence import SourceProvenanceEvidence
from forex_agent.domain.timestamps import UtcTimestamp


class SourceAttributionOutcome(Enum):
    """What `RecordSourceAttribution` actually did (mirrors
    `NewsSemanticAnnotationOutcome`)."""

    CREATED = "CREATED"
    REVISION_ADDED = "REVISION_ADDED"
    UNCHANGED = "UNCHANGED"


@dataclass(frozen=True, slots=True)
class SourceAttributionRecordResult:
    news_item_key: str
    role: SourceAttributionRole
    outcome: SourceAttributionOutcome
    attribution_vintage: SourceAttributionVintage
    """The relevant vintage after this call: the newly-written one for
    `CREATED`/`REVISION_ADDED`, or the EXISTING one for `UNCHANGED`."""


class OutOfOrderSourceAttributionError(Exception):
    """Raised when an incoming attribution vintage claims an
    `availability` earlier than this `(news_item_key, role)` pair's
    own latest recorded vintage."""

    def __init__(
        self,
        news_item_key: str,
        role: SourceAttributionRole,
        latest_availability: UtcTimestamp,
        incoming_availability: UtcTimestamp,
    ) -> None:
        self.news_item_key = news_item_key
        self.role = role
        self.latest_availability = latest_availability
        self.incoming_availability = incoming_availability
        super().__init__(
            f"attribution for news_item_key={news_item_key!r}, role={role.value!r} claims "
            f"availability={incoming_availability.value.isoformat()}, earlier than the latest "
            f"recorded vintage's own availability={latest_availability.value.isoformat()} -- "
            "refusing to append a backdated attribution"
        )


class SourceAttributionDeterminismError(Exception):
    """Raised when the SAME `(news_item_key, role, evidence_basis_
    revision_sequence, algorithm_version, evidence)` historical basis
    produces a DIFFERENT `(status, attributed_source_key)` than SOME
    ALREADY-STORED vintage for that exact basis -- checked across this
    `(news_item_key, role)` pair's ENTIRE stored history (FX-59H's own
    full-history rationale, directly mirrored). A genuinely different
    `evidence` object (e.g. a correction) is a different basis and
    never raises this."""

    def __init__(
        self,
        news_item_key: str,
        role: SourceAttributionRole,
        evidence_basis_revision_sequence: int,
        algorithm_version: str,
        evidence: SourceProvenanceEvidence,
        existing_status: SourceAttributionStatus,
        existing_attributed_source_key: str | None,
        incoming_status: SourceAttributionStatus,
        incoming_attributed_source_key: str | None,
    ) -> None:
        self.news_item_key = news_item_key
        self.role = role
        self.evidence_basis_revision_sequence = evidence_basis_revision_sequence
        self.algorithm_version = algorithm_version
        self.evidence = evidence
        self.existing_status = existing_status
        self.existing_attributed_source_key = existing_attributed_source_key
        self.incoming_status = incoming_status
        self.incoming_attributed_source_key = incoming_attributed_source_key
        super().__init__(
            f"news_item_key={news_item_key!r}, role={role.value!r}, evidence_basis_revision_"
            f"sequence={evidence_basis_revision_sequence}, algorithm_version="
            f"{algorithm_version!r}, evidence={evidence!r} already produced a DIFFERENT "
            f"attribution: existing=({existing_status.value!r}, "
            f"{existing_attributed_source_key!r}), incoming=({incoming_status.value!r}, "
            f"{incoming_attributed_source_key!r}) -- the SAME evidence evaluated under the SAME "
            "policy version must never produce two different attributions"
        )


class RecordSourceAttribution:
    """FX-62's own append-only source-attribution-recording use case
    -- see the module docstring."""

    def __init__(self, repository: SourceRegistryRepository) -> None:
        self._repository = repository

    async def __call__(
        self,
        news_item_key: str,
        role: SourceAttributionRole,
        availability: UtcTimestamp,
        algorithm_version: str,
        status: SourceAttributionStatus,
        attributed_source_key: str | None,
        evidence_basis_revision_sequence: int,
        evidence: SourceProvenanceEvidence,
        *,
        corrects_revision_sequence: int | None = None,
        dry_run: bool = False,
    ) -> SourceAttributionRecordResult:
        """`dry_run=True` computes and returns the EXACT SAME outcome a
        real call would, using the EXACT SAME decision logic below,
        but never writes."""
        latest = await self._repository.latest_attribution_for_role(news_item_key, role)

        if latest is not None and availability.value < latest.availability.value:
            raise OutOfOrderSourceAttributionError(
                news_item_key, role, latest.availability, availability
            )

        history = await self._repository.list_attribution_vintages(news_item_key, role)
        for historical in history:
            if (
                historical.evidence_basis_revision_sequence == evidence_basis_revision_sequence
                and historical.algorithm_version == algorithm_version
                and historical.evidence == evidence
                and (historical.status, historical.attributed_source_key)
                != (status, attributed_source_key)
            ):
                raise SourceAttributionDeterminismError(
                    news_item_key,
                    role,
                    evidence_basis_revision_sequence,
                    algorithm_version,
                    evidence,
                    historical.status,
                    historical.attributed_source_key,
                    status,
                    attributed_source_key,
                )

        if latest is None:
            created = SourceAttributionVintage(
                news_item_key=news_item_key,
                role=role,
                revision_sequence=0,
                availability=availability,
                algorithm_version=algorithm_version,
                status=status,
                attributed_source_key=attributed_source_key,
                evidence_basis_revision_sequence=evidence_basis_revision_sequence,
                evidence=evidence,
                corrects_revision_sequence=corrects_revision_sequence,
            )
            if dry_run:
                return SourceAttributionRecordResult(
                    news_item_key, role, SourceAttributionOutcome.CREATED, created
                )
            write_result = await self._repository.add_attribution_vintage(created)
            outcome = (
                SourceAttributionOutcome.CREATED
                if write_result.inserted
                else SourceAttributionOutcome.UNCHANGED
            )
            return SourceAttributionRecordResult(news_item_key, role, outcome, created)

        if (
            latest.evidence_basis_revision_sequence == evidence_basis_revision_sequence
            and latest.algorithm_version == algorithm_version
            and latest.evidence == evidence
        ):
            # The historical determinism check above already proved
            # (status, attributed_source_key) == (latest.status, latest.
            # attributed_source_key) here, exactly mirroring FX-59
            # Section 52's own idempotent-reclassification reasoning --
            # `evidence` is included in this comparison (unlike FX-59's
            # own basis+algorithm_version-only check) because a
            # DIFFERENT evidence object under the SAME basis+algorithm
            # is a legitimate correction (Section 9), which must always
            # mint a new revision even if it happens to reassert the
            # SAME status/attributed_source_key as latest.
            return SourceAttributionRecordResult(
                news_item_key, role, SourceAttributionOutcome.UNCHANGED, latest
            )

        revised = SourceAttributionVintage(
            news_item_key=news_item_key,
            role=role,
            revision_sequence=latest.revision_sequence + 1,
            availability=availability,
            algorithm_version=algorithm_version,
            status=status,
            attributed_source_key=attributed_source_key,
            evidence_basis_revision_sequence=evidence_basis_revision_sequence,
            evidence=evidence,
            corrects_revision_sequence=corrects_revision_sequence,
        )
        if dry_run:
            return SourceAttributionRecordResult(
                news_item_key, role, SourceAttributionOutcome.REVISION_ADDED, revised
            )
        write_result = await self._repository.add_attribution_vintage(revised)
        outcome = (
            SourceAttributionOutcome.REVISION_ADDED
            if write_result.inserted
            else SourceAttributionOutcome.UNCHANGED
        )
        return SourceAttributionRecordResult(news_item_key, role, outcome, revised)
