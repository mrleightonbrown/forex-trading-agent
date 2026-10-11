# ADR 0007: PIT-Safe News Canonicalization & Conservative Deduplication (FX-58)

## Status

**Accepted (architecture) -- code/schema/tests complete and merged,
2026-10-11. Real-data activation BLOCKED pending review** -- the
required pre-persistence dry-run safety gate (Section 42/43 of this
story's own spec) found that the v1 automatic matcher's `EXACT_
HEADLINE_AND_SUMMARY` rule produces confirmed false-positive proposals
against real, already-ingested data (see "Real-data finding" below).
Per this story's own explicit instruction ("If ANY proposed pair is
actually related but distinct: STOP... Return the pair and matching
evidence for architecture review"), **zero relations were persisted
against the real database**; `news_canonical_relation_vintages`
remains empty. The architecture itself (the relation model, PIT
semantics, group derivation, the URL/body matching rules) is sound
and fully tested; the ONE matching rule found unsafe in practice is
flagged below for a future, separately-authorized correction before
any real write-mode run is attempted.

## Context

FX-57 (now fully closed) gave FTA six independent, source-native news
ingestion pipelines (Fed/ECB/BoE/GOV.UK/StatCan/BoC), each producing
its own `NewsItem`/`NewsItemVintage` history under its own source
identity. Nothing in that layer, by design, ever asks "do two
DIFFERENT source items, from the same or different providers,
describe the same underlying news story?" FX-58 answers exactly that
question, as a DERIVED evidence layer -- never by mutating,
merging, or repointing the source-native identities FX-56/FX-57
already established as permanent and independently recoverable.

## Decision

1. **`NewsItem` remains one source-native item, forever.** Canonical-
   ization never merges `NewsItem` rows, repoints `NewsSourceMapping`s,
   deletes a "duplicate" item, moves a source identity between items,
   rewrites `news_item_key`, chooses one publisher's item over
   another and discards it, changes `first_seen_at`, or modifies an
   existing `NewsItemVintage`. The existing (as of this story) 358
   source-native items remain exactly as FX-57 left them, independently
   recoverable, with no new column anywhere on any `news_items`/`news_
   item_vintages` row.

2. **Duplicate knowledge is represented as append-only pairwise
   relation vintages, never a persisted mutable "canonical group."**
   One new table, `news_canonical_relation_vintages`
   (`domain.news_canonical_relation_vintage.NewsCanonicalRelation
   Vintage`): `(left_news_item_key, right_news_item_key)` ordered
   lexicographically (`left < right`, enforced by both a domain
   check and a DB `CHECK` constraint; self-relations forbidden),
   `revision_sequence`, `availability`, `relation_kind` (`SAME_STORY`
   / `NOT_SAME_STORY`), `method` (`EXACT_CANONICAL_URL` /
   `EXACT_BODY_TEXT` / `EXACT_HEADLINE_AND_SUMMARY` / `MANUAL_
   REVIEW`), `left_item_revision_sequence`/`right_item_revision_
   sequence` (composite foreign keys into `news_item_vintages
   (news_item_key, revision_sequence)` -- pinning the EXACT two
   vintages compared, never copying their content), and `algorithm_
   version` (a stable label, e.g. `"fx58_v1"`, never a git commit
   hash). No application code path ever issues an `UPDATE` against
   this table -- a correction is a new revision, exactly like every
   other FX-56/FX-58 vintage type.

3. **`availability` is ALWAYS FTA's own decision time, never any
   source timestamp.** `CanonicalizeNewsOnce` captures `run_at`
   exactly once per run (an injected `ClockFn`, defined locally in
   the application layer rather than importing the HTTP-adapter-
   specific one `infrastructure.news_sources.http_fetch` owns, to
   respect the `domain -> application -> infrastructure` dependency
   direction) and uses that SAME instant for every relation decision
   that run produces.

4. **Canonical groups are DERIVED connected components, computed
   fresh on every query, never persisted as a mutable master row.**
   `domain.news_canonical_grouping.derive_canonical_groups` builds a
   union-find over `SAME_STORY` edges across every `NewsItem` known
   as of a requested instant, then fails closed
   (`NewsCanonicalizationInconsistentStateError`) if a `NOT_SAME_
   STORY` edge would otherwise land inside one component via
   transitivity. The group key is deterministic: the member with the
   earliest `NewsItem.first_seen_at`, tie-broken lexicographically --
   never interpreted as "most trustworthy source" (that is FX-EPIC-
   09's own future job).

5. **`NOT_SAME_STORY` corrections are append-only, never automatic.**
   The automatic matcher (`CanonicalizeNewsOnce`) NEVER writes `NOT_
   SAME_STORY` for a non-matching pair -- absence of a `SAME_STORY`
   match is never treated as an explicit "these are different"
   assertion. `NOT_SAME_STORY` may only ever be written with `method=
   MANUAL_REVIEW` (enforced by the domain type's own `__post_init__`
   and a DB `CHECK` constraint) -- no manual UI exists in FX-58, but
   the schema is already capable of representing a future audited
   correction without redesign. If the pair's latest relation is
   `NOT_SAME_STORY`, the automatic matcher is blocked from overturning
   it (`BLOCKED_BY_REVIEW_OVERRIDE`, counted and reported, never
   raised as an error) -- only a future explicit `MANUAL_REVIEW` call
   may reverse a reviewed decision.

6. **Contradictory stored graph state fails closed, never silently
   resolved either direction.** A-SAME-B, B-SAME-C, A-NOT_SAME-C
   raises `NewsCanonicalizationInconsistentStateError` from group
   derivation -- never silently merged into `{A,B,C}`, never silently
   ignoring the correction.

7. **The v1 automatic matcher (`fx58_v1`) is deliberately exact,
   high-precision, low-recall.** Exactly three rules, in fixed
   precedence (`EXACT_CANONICAL_URL` > `EXACT_BODY_TEXT` >
   `EXACT_HEADLINE_AND_SUMMARY`), each requiring byte-for-byte
   equality after a MINIMAL, non-fuzzy normalization (`domain.news_
   text_normalization`: Unicode NFKC, HTML-entity unescape, whitespace
   collapse, casefold for text; scheme/host lowercasing, fragment
   discard, everything else preserved verbatim -- including ECB's own
   deliberate double-slash path -- for URLs) plus a minimum length
   (body >= 200 chars, summary >= 80 chars) to exclude boilerplate
   fragments. A missing field on either side simply does not
   participate; it never makes an item invalid.

8. **No fuzzy, semantic, or ML/LLM matching of any kind exists or is
   planned for v1.** No cosine similarity, embeddings, token overlap,
   edit distance, TF-IDF, external AI API, or confidence score.
   Deterministic and reproducible by construction.

9. **Candidate input uses the EXISTING FX-56 evidence-eligible PIT
   semantics unmodified -- not a second interpretation.** `list_
   candidates_as_of` calls `NewsRepository.latest_evidence_eligible_
   vintage_as_of` directly. Its ACTUAL, already-shipped behavior
   (confirmed by reading the production SQL, not assumed from this
   story's own draft spec) is: if an item's current latest vintage is
   quarantined but an EARLIER vintage was evidence-eligible, that
   earlier vintage is still compared -- the item is excluded entirely
   only when NO vintage, as of the query instant, is evidence-
   eligible. `include_backfill=False` by default, matching that
   method's own default.

10. **`EconomicEvent` linkage remains explicitly deferred.** FX-52
    remains DEFER and there is no production full economic-calendar
    dataset suitable for trustworthy canonical linkage; FX-58 never
    manufactures an `EconomicEventOccurrence` identity from a news
    headline, and creates no `NewsItem -> EconomicEventOccurrence`
    link of any kind.

## Real-data finding: `EXACT_HEADLINE_AND_SUMMARY` is unsafe against recurring institutional boilerplate (BLOCKS activation)

The spec's own required pre-persistence dry-run (`scripts/
canonicalize_news.py --dry-run` against the real dev database, 358
genuine `NewsItem`s, 63,903 candidate pairs) proposed exactly 7
`SAME_STORY` pairs, ALL via `EXACT_HEADLINE_AND_SUMMARY` (zero via
`EXACT_CANONICAL_URL`/`EXACT_BODY_TEXT`). Direct inspection of the
underlying stored evidence for every proposed pair found:

- **3 Bank of Canada pairs** (among the June 10, July 15, and
  September 2, 2026 rate-decision press releases): all three carry
  the IDENTICAL boilerplate summary ("The Bank of Canada today held
  its target for the overnight rate at 2.25%, with the Bank Rate at
  2.5% and the deposit rate at 2.20%.") purely because the rate did
  not change across three SEPARATE, genuinely distinct monetary-
  policy decisions. **Confirmed false positive** -- exactly the
  "recurring institutional headline" hazard this story's own Section
  23 warned about, which the `EXACT_HEADLINE_AND_SUMMARY` rule's
  summary-equality requirement does NOT protect against when the
  SOURCE's own summary field is itself templated/outcome-boilerplate
  rather than genuinely free per-event text.
- **3 Federal Reserve pairs** (Powell semiannual testimony across
  March 2024/June 2025/February 2025/July 2024; Barr supervision
  testimony across May 2024/November 2024): the "summary" field is a
  standing committee-name boilerplate ("Testimony Before the
  Committee on Financial Services, U.S. House of Representatives")
  reused verbatim across many genuinely different hearing dates.
  **Confirmed false positive**, same root cause as the BoC pairs.
- **1 GOV.UK/HMT pair** ("More overseas firms enticed to buy
  British," published the same day six hours apart, URLs differing
  only by GOV.UK's own `--2` duplicate-slug disambiguation suffix):
  plausibly a genuine CMS republish of the SAME announcement, but
  this could not be confirmed with certainty from the stored evidence
  alone -- reported as ambiguous, not confirmed either way.

**6 of 7 proposed pairs are CONFIRMED related-but-distinct
publications, not duplicates.** Per this story's own explicit
instruction, this halts activation: no source-specific exception was
added casually, the threshold was not weakened or strengthened to
engineer a different outcome, and the first real persistent write-
mode run was never executed. `news_canonical_relation_vintages`
remains empty; all 358 pre-existing source rows are confirmed
untouched.

**This is reported as an architecture finding requiring a separately-
authorized follow-up, not fixed unilaterally in this story** -- per
CLAUDE.md's own "document the issue, explain the proposed change, and
stop before implementing an architectural change" instruction. A
plausible future direction (not decided here): require corroboration
from a field less prone to institutional boilerplate (e.g. `EXACT_
BODY_TEXT` only, dropping `EXACT_HEADLINE_AND_SUMMARY` as an
automatic v1 rule entirely; or detecting and excluding a per-source
"known boilerplate summary" set, analogous to StatCan's own known-
catalogue-reference exclusion in FX-57EH) -- but choosing between
these is exactly the kind of matching-policy decision this ADR
defers to a future, explicitly-authorized `fx58_v1` correction (NOT
silently reinterpreted as `fx58_v1` itself) or `fx58_v2`.

## Consequences

- The relation model, schema, migration (with its own downgrade
  guard), repository, and all four use cases (`RecordNewsCanonical
  Relation`, `CanonicalizeNewsOnce`, `GetCanonicalNewsGroupsAsOf`,
  plus the pure domain matcher/grouping functions) are complete,
  fully unit- and Postgres-integration-tested (91 new tests), and
  ready to run the moment the `EXACT_HEADLINE_AND_SUMMARY` finding
  above is resolved.
- `scripts/canonicalize_news.py --dry-run` is the required safety
  gate before ANY future write-mode run against real data, and MUST
  be re-run (and its output re-reviewed by a human) after any change
  to the matching rules, not only once at this story's own end.
- FX-59 (relevance/entities/topics), FX-60 (pair-specific news
  snapshot), FX-61 (Market Context visualization), and FX-EPIC-09
  (source reputation) all remain unauthorized to start -- none of
  them depend on FX-58 having ANY persisted relation yet, since
  "zero relations" is an explicitly valid, honestly-reported FX-58
  outcome, not a blocking failure of this story itself.

## Alternatives considered

- **A persisted, mutable `canonical_news_item_id` column on
  `NewsItem`, or a separate mutable "canonical group" table.**
  Rejected (Section 4/11): either shape requires a destructive-merge
  or master-record-reassignment operation somewhere, reopening
  exactly the class of orphan-row/race/lineage problems this
  project's own FX-52A/FX-52AH/FX-56H history already paid down once;
  a derived, recomputed-on-read connected-component view has none of
  those failure modes.
- **Weakening or dropping the minimum-length thresholds to force a
  real-data duplicate cluster to appear.** Rejected outright (Section
  43's own explicit prohibition) -- "zero proposed pairs is a VALID
  result," and manufacturing a cluster to prove the pipeline "does
  something" would defeat the entire high-precision design goal.
- **Silently narrowing `EXACT_HEADLINE_AND_SUMMARY` inside this same
  story once the real-data finding above surfaced.** Rejected --
  doing so without the explicit architecture review this ADR is
  itself the vehicle for would repeat exactly the mistake FX-57C's
  own "documented but still wrong" fallback made (see `docs/
  DECISIONS.md`'s FX-57CH entry): a quiet in-story fix is not a
  substitute for an explicitly reviewed, explicitly versioned
  (`fx58_v2`) policy change.
