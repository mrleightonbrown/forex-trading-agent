# ADR 0009: PIT-Safe Pair-Specific News Evidence Snapshot (FX-60)

## Status

**Accepted -- code/tests complete, 2026-10-12.** FX-60 introduces no
schema and no migration (Section 2): it is a derived, on-demand read
model recomputed from FX-56/57's own news storage, FX-58's own
canonical story groups, and FX-59's own semantic annotation state.
The required real-data safety check (Section 83) was run against
EUR/USD, GBP/USD, and USD/CAD over the full 358-item real dataset;
every `BOTH`-side entry, every explicit-institution-mention entry,
and a deterministic sample of `BASE_ONLY`/`QUOTE_ONLY` entries were
inspected directly against the underlying FX-59 `currency_relevance`
output and confirmed genuine -- zero false positives, zero
aggregation-rule corrections needed.

**FX-60H (contract hardening) accepted, 2026-10-12** -- see the
addendum below. `fx60_v1` preserved unchanged; no PIT, grouping,
window, relevance, or semantic-eligibility rule changed.

## Context

FX-58 answers "do two source-native items represent the SAME
underlying story?" FX-59 answers "what is one item ABOUT?" Neither
answers the question a trading-facing view actually needs: "for THIS
currency pair, what CURRENT news evidence does FTA know, within an
explicit time window?" FX-60 answers exactly that, strictly as a
presentation-layer PROJECTION over the other three layers -- it
creates no new fact of its own, and decides nothing about direction,
importance, or trustworthiness.

## Decisions

**1. FX-60 is an on-demand derived read model, not persisted
state.** No new SQLAlchemy model, no Alembic migration, no snapshot
write repository, no append-only snapshot vintage. Every call to
`GetPairNewsEvidenceSnapshot` recomputes its answer fresh from
`NewsRepository`/`NewsCanonicalizationRepository`/`NewsSemantic
Repository` -- the same historical instant always reproduces the
same answer, without needing a cache or a materialized table.

**2. One explicit `as_of` governs every constituent query.** The use
case never calls `UtcTimestamp.now()`; `as_of` is the caller's own
single PIT cut, threaded unchanged through canonical-group
derivation, vintage-eligibility lookups, and semantic-state queries.

**3. Window policy is caller-supplied, never hidden.** `window_start`/
`as_of` are both required parameters -- no internal 24h/48h/72h
default exists. A future caller (FX-61) chooses its own policy; FX-60
never invents one on its behalf.

**4. Window recency uses FTA's own `NewsItem.first_seen_at`, never
provider publication timestamps.** `source_published_at` may be
displayed but never controls visibility, window membership,
deduplication, or ordering -- confirmed by a dedicated worked example
where an item's `source_published_at` claims a date far outside the
window while `first_seen_at` keeps it correctly included, and the
reverse.

**5. FX-58 canonical grouping happens BEFORE pair presentation.**
Individual source-native `NewsItem`s are never surfaced first and
deduplicated after the fact; `derive_canonical_groups` runs first, and
one canonical group produces at most one pair-evidence entry.

**6. Late duplicate representations never revive an old story.**
`story_first_seen_at` is the MINIMUM `first_seen_at` among a group's
own snapshot-eligible members -- when a later-arriving duplicate
merges into an existing group, the merged story's own age is still
anchored to the EARLIEST member, even if that member was previously
invisible as a separate group. Pinned by the mandatory window/dedup
worked example (a story merging two items eight hours apart, with the
window drawn to admit only the later one): once the `SAME_STORY`
relation is known, the merged group's own anchor moves to the earlier
instant and the story correctly falls OUTSIDE the window.

**7. Snapshot eligibility uses evidence-eligible PROSPECTIVE news
only.** A member with no qualifying `NewsRepository.latest_evidence_
eligible_vintage_as_of` result (quarantined, or `BACKFILL`-only unless
explicitly requested) contributes nothing at all -- not to pair
evidence, not to the window-anchor computation, not to a semantic
gap. A `BACKFILL`-only member that would otherwise be a group's
earliest member is excluded entirely, so excluded historical evidence
can never make a genuinely prospective story look artificially old.

**8. Pair relevance comes ONLY from FX-59's own `currency_relevance`,
never re-derived.** `domain.news_pair_relevance.classify_pair_
relevance` is a pure function over already-decided FX-59 output; it
never re-runs institution/jurisdiction/alias/text-search logic, and
never infers relevance from entities or topics alone.

**9. `STALE`/`UNCLASSIFIED` mean UNKNOWN relevance, never
"irrelevant."** Only `NewsSemanticState.CURRENT` members may
contribute currency relevance, topics, or entities to a pair-evidence
entry. A `STALE`/`UNCLASSIFIED` member is surfaced as a `NewsPair
SemanticGap` diagnostic instead -- even inside a canonical group that
has no OTHER pair-relevant member, so a genuinely unknown relevance
is never silently reported as a confirmed absence.

**10. Semantic incompleteness is surfaced explicitly, never hidden.**
`NewsPairSemanticCoverage.INCOMPLETE_SEMANTICS` is reported whenever
any in-window, snapshot-eligible member across ANY considered group
is `STALE`/`UNCLASSIFIED` -- independent of whether that member's own
group happens to be pair-relevant.

**11. Source withdrawal is separated from active evidence, never
deleted.** A relevant `CURRENT` member whose exact basis
`NewsItemVintage` has `source_status = WITHDRAWN` is tracked
separately (`withdrawn_relevant_member_keys`); a group with at least
one relevant `ACTIVE` member is an active entry, a group with only
relevant `WITHDRAWN` members becomes a withdrawn-only entry, and a
group with both keeps full member-level status detail. Withdrawal
never means "negative" or "discredited" -- lifecycle provenance only.

**12. Base/quote relevance carries no direction or sentiment.**
`NewsPairRelevanceSide` (`BASE_ONLY`/`QUOTE_ONLY`/`BOTH`) is purely
categorical location evidence -- confirmed by a dedicated field-
surface introspection test across every new DTO, asserting no
`direction`/`sentiment`/`stance`/`bias`/`*_score`/`importance` field
exists anywhere in this story's own output types.

**13. No score, weighting, source reputation, or importance exists.**
No duplicate-count-based "strength," no source trust/rank, no 0-100
impact label. Canonicalization already prevents duplicate source
representations from being double-counted; `FX-EPIC-09` owns source
reputation as a separate, later concern.

**14. FX-60 does not join economic events or other evidence
families.** No `EconomicEventOccurrence` linkage, no market-regime/
strategy-signal/policy-rate-differential merge. FX-60 produces the
NEWS evidence family only; the Decision Engine is responsible for
combining evidence families later.

**15. Pair-specific presentation is the input surface for FX-61.**
`GetPairNewsEvidenceSnapshot`'s own output is intentionally
presentation-ready (bounded member detail, no `body_text`,
deterministic sort order) so a future Market Context extension can
consume it directly without inventing its own aggregation logic.

## Real-data finding

The required real-data safety check (Section 83) was run against
EUR/USD (69 active entries, 289 pair-irrelevant groups, 0 withdrawn,
0 gaps, `COMPLETE` coverage), GBP/USD (215 active entries, one `BOTH`
entry), and USD/CAD (167 active entries, zero `BOTH` entries). Every
`BOTH` entry was inspected directly: GBP/USD's own sole `BOTH` entry
is a genuine Bank of England speech explicitly discussing "US dollar
dominance" (GBP source + USD explicit mention); EUR/USD and USD/CAD
had none. A deterministic sample of `BASE_ONLY`/`QUOTE_ONLY` entries
was spot-checked against each item's own stored `currency_relevance`
and confirmed correct, including consolidated multi-reason entries
(e.g. a Bank of Canada press release carrying both `SOURCE_
JURISDICTION` and `EXPLICIT_INSTITUTION_MENTION` for CAD, since the
release's own text names "Bank of Canada" explicitly in addition to
being published by it). Zero withdrawn-only entries and zero semantic
gaps existed in the real data at inspection time (no source has ever
reported a withdrawal; all 358 items carry `CURRENT` semantics as of
`now`), so those diagnostic categories were exercised exclusively
through the real-Postgres PIT worked examples, not the live corpus.

## Consequences

- `358 = 69 (EUR/USD active) + 289 (EUR/USD pair-irrelevant)`,
  confirming every one of the 358 real canonical groups (all
  singletons, since 0 canonical relations exist today) was accounted
  for by the snapshot's own counters.
- FX-61 (Market Context dashboard) may now consume `GetPairNews
  EvidenceSnapshot` directly for its own pair-specific news
  presentation, pending separate authorization.
- No existing FX-56/57/58/58H/59/59H file, table, or migration was
  touched; `news_items`/`news_semantic_annotation_vintages`/`news_
  canonical_relation_vintages` remain at `358`/`358`/`0` respectively,
  confirmed unchanged before and after every real-data run in this
  story.

## FX-60H addendum (2026-10-12): complete accounting, relation
provenance, and O(1) query cost

**Finding 1 (incomplete accounting).** FX-60's own original
implementation never counted a canonical group that had a semantic
gap (a `STALE`/`UNCLASSIFIED` member) but NO member confirming pair
relevance anywhere in the group. Such a group's own disposition was
previously implicit -- visible only via `len(semantic_gaps)`, never
reconciled against `groups_considered`. An auditor could not verify
the snapshot's own arithmetic from its headline fields alone.

**Finding 2 (opaque canonical membership).** `NewsPairEvidenceGroup`
exposed WHICH items belonged to a multi-member group, but not WHY --
the FX-58 `SAME_STORY` relation vintage(s) that justified the merge
were not surfaced, so a caller/auditor had to re-query FX-58 directly
to explain a transitive group's own membership.

**Finding 3 (N+1 query shape).** The original per-group loop called
`latest_evidence_eligible_vintage_as_of` once per member, and for
every group that passed the window/eligibility gates, called `GetNews
SemanticStatesAsOf` once per group -- which itself issued `latest_
annotation_as_of` AND a REDUNDANT second `latest_evidence_eligible_
vintage_as_of` call per member. Measured directly against the real
358-item corpus (`before_cursor_execute` event counting, no mocking):
**1076 SQL round trips** for the original implementation versus
**4** for the hardened one -- confirmed again at a smaller, real
110-item population cut (**222** versus **4**), demonstrating growth
with population size in the original path and a constant cost in the
hardened one.

**Correction.**

- `NewsPairSnapshotAccounting` (new, additive-only field `accounting`
  on `NewsPairEvidenceSnapshot`) gives every one of `groups_total`
  canonical groups EXACTLY ONE of seven mutually-exclusive
  dispositions -- `groups_outside_window`/`groups_without_eligible_
  evidence`/`groups_pair_irrelevant`/`groups_incomplete_semantics`/
  `groups_base_only`/`groups_quote_only`/`groups_both` -- enforced
  structurally in `__post_init__`, so the sum reconciling to
  `groups_total` is an invariant, not a convention. `groups_
  incomplete_semantics` is the new bucket Finding 1 required: a group
  with unresolved semantic relevance is never counted as confirmed
  irrelevant.
- `NewsPairEvidenceGroup` gains `relation_provenance: tuple[NewsCanon
  icalRelationVintage, ...]` -- the REAL FX-58 `SAME_STORY` relation
  rows connecting this group's own members, reused directly from the
  SAME `list_latest_relation_states_as_of(as_of)` call already made
  for grouping (no new query, no new DTO, no new persistence). Empty
  for a singleton group; for a transitive 3-member group it lists
  exactly the real edges that justify the merge, never a synthesized
  edge for a pair with no direct relation.
- The per-item/per-group repository access pattern is replaced with
  exactly TWO new batch repository methods -- `latest_evidence_
  eligible_vintages_as_of`/`latest_annotations_as_of`, added to the
  existing `SqlAlchemyNewsRepository`/`SqlAlchemyNewsSemanticReposi
  tory` concrete classes -- called ONCE each for the entire snapshot,
  declared via two LOCAL `Protocol`s in the use case's own module
  (`_VintageLookup`/`_SemanticAnnotationLookup`) rather than widening
  the global `NewsRepository`/`NewsSemanticRepository` ports used by
  every other caller. Semantic-state classification (`CURRENT`/
  `STALE`/`UNCLASSIFIED`) is now computed locally against the SAME
  already-fetched vintage via a new pure function (`_resolve_semantic_
  state`), eliminating the redundant second fetch Finding 3
  identified. `GetNewsSemanticStateAsOf`/`GetNewsSemanticStatesAsOf`
  (FX-59's own files) are completely untouched -- this is a new,
  parallel, more efficient path used only by this use case; FX-59's
  own single-item query surface is unaffected for any other caller.

**Verification.** Every pre-existing FX-60 PIT worked example (same-
story/not-same-story relation PIT, transitive/contradictory grouping,
the critical late-duplicate window/dedup example, correction-does-
not-revive, source-published-time independence, semantic-availability
PIT, stale-semantics PIT, backfill window-anchor exclusion, algorithm-
version PIT, the full-chain no-mutation proof) passed unmodified
against both the in-memory fakes and real Postgres. New tests added:
synthetic-fixture accounting reconciliation across singleton,
duplicate, mixed active/withdrawn, out-of-window, no-eligible-
evidence, confirmed-irrelevant, and incomplete-semantics group shapes
(including two direct `NewsPairSnapshotAccounting` construction-
rejection tests); relation-provenance tests for singleton/pair/
transitive groups plus an explicit real-Postgres PIT proof that a
relation added after a requested `as_of` cannot appear in an earlier
snapshot's own provenance; a dedicated real-Postgres equivalence
suite (`tests/integration/test_news_repository_batch_lookups.py`)
proving the two new batch repository methods produce results
byte-identical to their existing single-item counterparts across
`CURRENT`/`STALE`/`UNCLASSIFIED`/revision/historical-`as_of` cases;
and a parametrized synthetic-population test (1/10/50/200 items)
proving repository round trips stay constant at exactly 4 regardless
of population size.

**Scope.** No schema, migration, PIT rule, canonical grouping rule,
window rule, relevance rule, or semantic-eligibility rule changed;
`fx60_v1` is preserved unchanged. No cache, materialized snapshot, or
unrelated schema change was introduced. The real 358-item corpus
(`news_items`/`news_semantic_annotation_vintages`/`news_canonical_
relation_vintages` = `358`/`358`/`0`) was confirmed unchanged before
and after this story, and the real EUR/USD (289 irrelevant + 23
base-only + 46 quote-only + 0 both = 358), GBP/USD (143 + 169 + 45 +
1 = 358), and USD/CAD (191 + 46 + 121 + 0 = 358) accounting totals
each reconcile exactly against it.
