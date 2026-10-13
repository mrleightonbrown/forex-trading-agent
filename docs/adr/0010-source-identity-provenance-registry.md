# ADR 0010: Source Identity & Provenance Registry (FX-62)

## Status

**Accepted -- code/schema/tests complete, and real-data bootstrap
COMPLETE, 2026-10-13.**

## Context

FX-55/56 established genuinely separate `NewsSourceIdentity`/
`NewsItem` provenance per technical ingestion feed; FX-58 derived
cross-source canonical story grouping; FX-59 derived item-level
semantic relevance (entities/topics/currency); FX-60/61 presented a
pair-specific evidence snapshot. None of these layers ever asked "WHO
is institutionally or personally responsible for this evidence" --
every one of them conflates a technical RSS/API feed (`FED`, `BOE`, ...)
with the publishing institution, and none can name an originating
claimant, commentator, or quoted actor distinct from the publisher.

FX-EPIC-09 ("Source Reputation & Forecast Performance") needs that
distinction as its own prerequisite foundation before any reliability
or forecast-performance metric (FX-63+) can be built on top of it.
FX-62 is explicitly Phase A of that epic: identity and attribution
infrastructure ONLY -- no scoring, no credibility, no trust, no
weighting. "Identity is not reputation. Attribution is not
endorsement. Publication is not necessarily authorship."

## Decisions

**1. Identity is a new, independent layer -- no FX-56-61 table is
touched.** `IntelligenceSource`/`SourceIdentityVintage`/
`SourceAttributionVintage` are three NEW tables (migration
`e23aac921014`): `intelligence_sources`, `source_identity_vintages`,
`source_attribution_vintages`. No existing `news_*` table gains a
column, an index, or a behavioral change. FX-57-61 are proven (by
regression suite) to work unchanged with an empty or partial FX-62
registry.

**2. Four source kinds, deliberately distinguishing technical
plumbing from the identities it carries.** `IntelligenceSourceKind`:
`ORGANIZATION`, `PERSON`, `PUBLICATION`, `TECHNICAL_FEED`. A
`TECHNICAL_FEED`-kind source may reuse FX-56/57's own feed
`source_key` string (e.g. `"BOE"`); an `ORGANIZATION`-kind source
reuses FX-59's own `institution_entity_key` convention (e.g.
`"BANK_OF_ENGLAND"`) -- genuinely different identity namespaces that
never collide for the six real sources (verified by a dedicated unit
test).

**3. `IntelligenceSource` is minimal and immutable; `SourceIdentity
Vintage` carries everything that can evolve, append-only -- mirroring
FX-56's own `NewsItem`/`NewsItemVintage` shape exactly.** `(source_key,
revision_sequence)` is the vintage's natural identity; no application
code path issues an `UPDATE` against either table.

**4. Attribution is role-scoped and status-explicit, never silently
defaulted.** `SourceAttributionRole`: `PUBLISHER`, `ORIGINATING_
CLAIMANT`, `QUOTED_ACTOR` -- a mentioned or quoted institution/person
is NEVER assumed to be the publisher or claimant without its own
explicit evidence. `SourceAttributionStatus` has deliberately only two
members, `CONFIRMED`/`UNRESOLVED` -- a correction (Decision 7) is
represented structurally as a NEW vintage, never a third `CORRECTED`
status. The domain type itself makes `CONFIRMED` without an
`attributed_source_key` (or `UNRESOLVED` with one) unconstructable.

**5. The full evidence object -- not merely its kind or a basis
revision number -- is part of the determinism key, for BOTH identity
and attribution.** FX-59's "same basis always yields same output"
assumption is a pure-function assumption that does not hold here: a
human can legitimately correct a prior confirmed identity fact or
attribution without the underlying `NewsItemVintage` or algorithm
changing at all (Decision 7's own worked example). The determinism
key is therefore `(source_key, algorithm_version, evidence)` for
identity and `(news_item_key, role, evidence_basis_revision_sequence,
algorithm_version, evidence)` for attribution: re-submitting the EXACT
SAME evidence under the SAME policy must always yield the SAME
output; genuinely different evidence (even of the same `evidence_
kind`) is a different historical basis and is never compared against
it. This was discovered via a failing test during implementation (see
Deviations below) and applied consistently to both use cases'
idempotent-no-op detection too, so a second independent confirmation
with different evidence always mints a new revision rather than being
silently dropped.

**6. Evidence provenance is restricted to four permitted kinds, with
LLM/NLP-inferred claimant identity explicitly prohibited.**
`SourceEvidenceKind`: `ADAPTER_CONFIGURATION`, `SOURCE_NATIVE_
METADATA`, `AUTHORITATIVE_REFERENCE`, `MANUAL_REVIEW`. No application
code anywhere derives a claimant/publisher identity via statistical
NLP, embeddings, or an LLM call.

**7. Publisher resolution never falls back to the technical feed.**
`ResolvePublisherForNewsItemAsOf` resolves strictly through the
`PUBLISHER`-role attribution chain; if no attribution was ever
recorded for an item, the result is `NOT_RECORDED`, never a silent
substitution of the ingesting feed's own identity (pinned by a
dedicated unit test). A fourth resolution state, `AMBIGUOUS`, is
retained in the type as an explicit, never-silently-resolved-by-row-
order state even though it is structurally unreachable under this
registry's own uniqueness constraints -- defense-in-depth per the
story's own explicit requirement, not a speculative feature.

**8. The six-source bootstrap table reuses FX-56/59's own existing
registries verbatim -- no third parallel mapping is invented.**
`INTELLIGENCE_SOURCE_BOOTSTRAP_MAPPINGS` (`domain.intelligence_
source_bootstrap_registry`) is built from `domain.news_source_
registry` (feed `source_key`) and `domain.news_semantic_source_
profile` (`institution_entity_key`, reused as the organization's own
`source_key`): FED->FEDERAL_RESERVE, ECB->EUROPEAN_CENTRAL_BANK,
BOE->BANK_OF_ENGLAND, GOVUK_HMT->HM_TREASURY, STATCAN->STATISTICS_
CANADA, BOC->BANK_OF_CANADA. FED's three distinct RSS channels
(press_monetary/speeches/testimony) were directly verified to be the
SAME institution before finalizing this 1:1 mapping -- no
heterogeneous-institution feed is silently flattened.

**9. Bootstrap never backdates knowledge, and preserves unmapped
sources as unresolved rather than guessing.** `BootstrapSourceRegistry`
uses its own caller-supplied `bootstrap_at` for every `registered_at`
-- never a candidate's own `basis_availability` -- and simply never
attributes a candidate whose `source_key` has no bootstrap mapping
entry (pinned by a dedicated unit test); it is deliberately fully
idempotent across repeated runs with `include_backfill=True` always
(a deviation from FX-60/61's own prospective-only default, justified
since publisher identity does not depend on observation mode).

**10. One combined repository port, not a split per concern.**
`SourceRegistryRepository` covers both identity and attribution
concerns in a single Protocol -- a deliberate departure from FX-58/
59's own "separate port per concern" precedent, justified because
attribution resolution directly depends on identity resolution.

**11. Atomic first-registration avoids FX-56's own race complexity
entirely, because no key-minting race exists here.** `source_key` is
always caller-supplied (bootstrap mapping table or manual input),
never repository-minted, so `register_source_with_first_identity_
vintage` only needs `INSERT ... ON CONFLICT DO NOTHING` on the source
row plus an atomic first-vintage insert in the same transaction --
simpler than FX-56's own orphan-race-avoidance pattern, verified
correct under real concurrent writes (`asyncio.gather`, two
independent sessions racing the same `source_key`).

**12. No credibility, trust, weighting, ranking, or sentiment
anywhere in this layer.** Confirmed CONFIRMED/UNRESOLVED attribution
status carries zero numeric or categorical quality judgment --
FX-63's own reliability metrics, and any future Decision/Risk Engine
use, are both explicitly out of scope here and unauthorized by this
story.

## Real-data bootstrap result

The real, already-ingested 358-item corpus (unchanged by this story)
was bootstrapped via `scripts/bootstrap_source_registry.py`:

- 12 durable `IntelligenceSource` rows: 6 `TECHNICAL_FEED` (FED, ECB,
  BOE, GOVUK_HMT, STATCAN, BOC) + 6 `ORGANIZATION` (FEDERAL_RESERVE,
  EUROPEAN_CENTRAL_BANK, BANK_OF_ENGLAND, HM_TREASURY, STATISTICS_
  CANADA, BANK_OF_CANADA), each with exactly one identity vintage.
- 358 `PUBLISHER`-role attribution vintages, all `CONFIRMED`, zero
  `UNRESOLVED`: FED->FEDERAL_RESERVE 45, ECB->EUROPEAN_CENTRAL_BANK 22,
  BOE->BANK_OF_ENGLAND 150, GOVUK_HMT->HM_TREASURY 20, STATCAN->
  STATISTICS_CANADA 111, BOC->BANK_OF_CANADA 10 (sums to 358, matching
  the corpus exactly).
- A second and third immediately-repeated real run both reported
  `feed_identities_created=0`, `organization_identities_created=0`,
  `total_attributions_created=0`, `total_attributions_unchanged=358`,
  confirming idempotency against the real database.
- The underlying `news_items`/`news_item_vintages` corpus was
  confirmed unchanged (358/358 before and after) -- this story only
  ever reads FX-56-59's own evidence, never writes to it.

## Consequences

- FX-63 (source reliability/forecast-performance metrics) is now
  explicitly cleared to begin, pending separate authorization -- it
  may read `ResolvePublisherForNewsItemAsOf`/`ResolveSourceAttributions
  AsOf` directly, per this ADR's own Decisions 7/10.
- FX-64 through FX-67 remain behind Gate G09, unaffected by this story.
- Identity assumption requiring future manual verification: the
  six-source bootstrap mapping assumes each feed's technical identity
  maps 1:1 to exactly one publishing organization. This holds for all
  six real sources today (confirmed by direct inspection of each
  adapter, including FED's three channels), but would need explicit
  review before any future feed is added whose technical channel
  genuinely mixes content from more than one institution.

## Deviations found during implementation

**Attribution determinism initially omitted `evidence` from its own
key**, mirroring FX-59's `(basis_revision, algorithm_version)` pattern
too literally. A unit test asserting that `PUBLISHER` and
`ORIGINATING_CLAIMANT` roles keep independent revision histories
(exercising the story's own Section 9 worked example: an `A`-naming
confirmation later corrected to `B` under the same basis/algorithm)
failed with a spurious `SourceAttributionDeterminismError`, because a
legitimate correction is indistinguishable from a non-deterministic
policy output under a key that excludes the evidence itself. Fixed by
including the full `evidence` object in the determinism key (Decision
5 above) for both identity and attribution, and applying the same fix
to each use case's own idempotent-no-op ("UNCHANGED") detection, which
shared the identical latent gap. No schema or migration change was
needed; this was caught and corrected entirely within application-
layer logic before any real data was written under the old key.
