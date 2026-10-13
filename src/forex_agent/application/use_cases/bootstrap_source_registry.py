"""FX-62 Section 6: idempotent seeding of the FX-62 source-identity
registry for the six existing, already-admitted news feeds, reusing
`domain.intelligence_source_bootstrap_registry`'s own already-reviewed
mapping table -- never a second, independently-guessed mapping.

For EACH of the six feeds, this use case:

1. Registers (or confirms already-registered, idempotently) a
   `TECHNICAL_FEED`-kind `IntelligenceSource` for the feed itself,
   reusing the SAME `source_key` FX-57's own `NewsSourceIdentity`
   already uses.
2. Registers (or confirms) an `ORGANIZATION`-kind `IntelligenceSource`
   for the feed's own publishing organization, reusing FX-59's own
   `institution_entity_key` as that organization's `source_key`.
3. For every `NewsItem` FTA has observed through that feed (reusing
   `NewsSemanticRepository.list_candidates_as_of` directly -- never a
   second, independently-interpreted item-enumeration query), records
   a `CONFIRMED` `PUBLISHER` attribution naming that organization,
   with `evidence_basis_revision_sequence` pinned to the EXACT latest
   evidence-eligible vintage FX-56/57/58's own evidence layer already
   established for that item.

**Read/write boundary (Section 11)**: reads `NewsSemanticRepository`
(an ALREADY-approved FX-59 port) strictly read-only -- never calls any
of its write methods, and never touches `NewsItem`/`NewsItemVintage`/
`NewsSemanticAnnotationVintage` storage. Writes flow ONLY through
`RecordSourceIdentityVintage`/`RecordSourceAttribution`, FX-62's own
approved application services -- never a raw repository write bypass.

**PIT discipline (Section 6)**: `bootstrap_at` is the caller's own
single, explicit instant -- captured ONCE by the caller (mirroring
every other use case in this codebase's own "never call `now()`
internally" discipline) and used as the `availability` for EVERY
identity/attribution vintage this run writes. Never backdated to an
item's own `first_seen_at` or an organization's own real-world
founding date (Section 6's own explicit "do not backdate identity
knowledge" requirement)."""

from dataclasses import dataclass, field
from typing import Protocol

from forex_agent.application.use_cases.record_source_attribution import (
    RecordSourceAttribution,
    SourceAttributionOutcome,
)
from forex_agent.application.use_cases.record_source_identity_vintage import (
    RecordSourceIdentityVintage,
    SourceIdentityOutcome,
)
from forex_agent.domain.intelligence_source_bootstrap_registry import (
    INTELLIGENCE_SOURCE_BOOTSTRAP_MAPPINGS,
    IntelligenceSourceBootstrapMapping,
)
from forex_agent.domain.intelligence_source_kind import IntelligenceSourceKind
from forex_agent.domain.news_semantic_classifying import NewsSemanticClassificationCandidate
from forex_agent.domain.source_attribution_role import SourceAttributionRole
from forex_agent.domain.source_attribution_status import SourceAttributionStatus
from forex_agent.domain.source_evidence_kind import SourceEvidenceKind
from forex_agent.domain.source_provenance_evidence import SourceProvenanceEvidence
from forex_agent.domain.timestamps import UtcTimestamp

ALGORITHM_VERSION = "fx62_v1"


class _CandidateLookup(Protocol):
    """FX-62 Section 11: the narrow structural requirement this use
    case actually needs from a `NewsSemanticRepository`-shaped
    collaborator -- satisfied directly by `SqlAlchemyNewsSemanticRepository`,
    which already implements this method. Deliberately NOT a widening
    of any global port (mirrors FX-60H's own narrow-local-Protocol
    precedent exactly)."""

    async def list_candidates_as_of(
        self, as_of: UtcTimestamp, *, include_backfill: bool = False
    ) -> tuple[NewsSemanticClassificationCandidate, ...]: ...


@dataclass(frozen=True, slots=True)
class SourceBootstrapMappingResult:
    mapping: IntelligenceSourceBootstrapMapping
    feed_identity_outcome: SourceIdentityOutcome
    organization_identity_outcome: SourceIdentityOutcome
    items_considered: int
    attributions_created: int
    attributions_unchanged: int


@dataclass(frozen=True, slots=True)
class BootstrapSourceRegistryResult:
    bootstrap_at: UtcTimestamp
    mapping_results: tuple[SourceBootstrapMappingResult, ...] = field(default_factory=tuple)

    @property
    def feed_identities_created(self) -> int:
        return sum(
            1
            for r in self.mapping_results
            if r.feed_identity_outcome is SourceIdentityOutcome.CREATED
        )

    @property
    def organization_identities_created(self) -> int:
        return sum(
            1
            for r in self.mapping_results
            if r.organization_identity_outcome is SourceIdentityOutcome.CREATED
        )

    @property
    def total_attributions_created(self) -> int:
        return sum(r.attributions_created for r in self.mapping_results)

    @property
    def total_attributions_unchanged(self) -> int:
        return sum(r.attributions_unchanged for r in self.mapping_results)

    @property
    def total_items_considered(self) -> int:
        return sum(r.items_considered for r in self.mapping_results)


class BootstrapSourceRegistry:
    """FX-62's own idempotent six-source bootstrap orchestrator -- see
    the module docstring."""

    def __init__(
        self,
        record_identity: RecordSourceIdentityVintage,
        record_attribution: RecordSourceAttribution,
        semantic_repository: _CandidateLookup,
    ) -> None:
        self._record_identity = record_identity
        self._record_attribution = record_attribution
        self._semantic_repository = semantic_repository

    async def __call__(
        self,
        bootstrap_at: UtcTimestamp,
        *,
        include_backfill: bool = True,
        dry_run: bool = False,
    ) -> BootstrapSourceRegistryResult:
        """`include_backfill=True` (unlike most FX-60/61 evidence
        reads) -- publisher identity does not depend on whether an
        item's own observation mode was `PROSPECTIVE` or `BACKFILL`;
        bootstrap's own job is to establish attribution for EVERY item
        FTA has ever observed through an admitted feed, not merely the
        prospective subset."""
        candidates = await self._semantic_repository.list_candidates_as_of(
            bootstrap_at, include_backfill=include_backfill
        )
        candidates_by_source_key: dict[str, list[NewsSemanticClassificationCandidate]] = {}
        for candidate in candidates:
            candidates_by_source_key.setdefault(candidate.source_key, []).append(candidate)

        mapping_results: list[SourceBootstrapMappingResult] = []
        for mapping in INTELLIGENCE_SOURCE_BOOTSTRAP_MAPPINGS:
            feed_result = await self._record_identity(
                source_key=mapping.feed_source_key,
                source_kind=IntelligenceSourceKind.TECHNICAL_FEED,
                registered_at=bootstrap_at,
                availability=bootstrap_at,
                algorithm_version=ALGORITHM_VERSION,
                display_name=mapping.feed_display_name,
                aliases=(),
                authoritative_identifier=None,
                canonical_website=None,
                evidence=SourceProvenanceEvidence(
                    evidence_kind=SourceEvidenceKind.ADAPTER_CONFIGURATION,
                    description=(
                        f"domain.news_source_registry source_key={mapping.feed_source_key!r} "
                        "(FX-56/ADR 0005-admitted technical feed)"
                    ),
                ),
                dry_run=dry_run,
            )

            organization_result = await self._record_identity(
                source_key=mapping.organization_source_key,
                source_kind=IntelligenceSourceKind.ORGANIZATION,
                registered_at=bootstrap_at,
                availability=bootstrap_at,
                algorithm_version=ALGORITHM_VERSION,
                display_name=mapping.organization_display_name,
                aliases=(),
                authoritative_identifier=None,
                canonical_website=None,
                evidence=SourceProvenanceEvidence(
                    evidence_kind=SourceEvidenceKind.ADAPTER_CONFIGURATION,
                    description=(
                        "domain.news_semantic_source_profile institution_entity_key="
                        f"{mapping.organization_source_key!r} for feed source_key="
                        f"{mapping.feed_source_key!r} (FX-59-reviewed institution mapping)"
                    ),
                ),
                dry_run=dry_run,
            )

            attributions_created = 0
            attributions_unchanged = 0
            items = candidates_by_source_key.get(mapping.feed_source_key, ())
            for candidate in items:
                attribution_result = await self._record_attribution(
                    news_item_key=candidate.news_item_key,
                    role=SourceAttributionRole.PUBLISHER,
                    availability=bootstrap_at,
                    algorithm_version=ALGORITHM_VERSION,
                    status=SourceAttributionStatus.CONFIRMED,
                    attributed_source_key=mapping.organization_source_key,
                    evidence_basis_revision_sequence=candidate.basis_news_item_revision_sequence,
                    evidence=SourceProvenanceEvidence(
                        evidence_kind=SourceEvidenceKind.ADAPTER_CONFIGURATION,
                        description=(
                            f"feed source_key={mapping.feed_source_key!r} is admitted and "
                            f"mapped to organization_source_key="
                            f"{mapping.organization_source_key!r} in "
                            "domain.intelligence_source_bootstrap_registry"
                        ),
                    ),
                    dry_run=dry_run,
                )
                if attribution_result.outcome is SourceAttributionOutcome.CREATED:
                    attributions_created += 1
                else:
                    attributions_unchanged += 1

            mapping_results.append(
                SourceBootstrapMappingResult(
                    mapping=mapping,
                    feed_identity_outcome=feed_result.outcome,
                    organization_identity_outcome=organization_result.outcome,
                    items_considered=len(items),
                    attributions_created=attributions_created,
                    attributions_unchanged=attributions_unchanged,
                )
            )

        return BootstrapSourceRegistryResult(
            bootstrap_at=bootstrap_at, mapping_results=tuple(mapping_results)
        )
