# ADR 0007: PIT-Safe News Canonicalization & Conservative Deduplication (FX-58)

## Status

**Accepted (architecture) -- code/schema/tests complete and merged,
2026-10-11. Real-data activation COMPLETE as of FX-58H (2026-10-11),
under the corrected `fx58_v2` policy** -- see this ADR's own FX-58H
addendum at the end of this document for the full correction record.
The original `fx58_v1` policy, described in the body of this ADR
below, NEVER reached real-data activation: the required pre-
persistence dry-run safety gate (Section 42/43 of FX-58's own spec)
found that its `EXACT_HEADLINE_AND_SUMMARY` rule produced confirmed
false-positive proposals against real, already-ingested data (see
"Real-data finding" below, preserved exactly as originally written --
this historical fact is not rewritten to imply `fx58_v1` had always
used a different policy). Per FX-58's own explicit instruction ("If
ANY proposed pair is actually related but distinct: STOP... Return
the pair and matching evidence for architecture review"), zero
relations were ever persisted under `fx58_v1`. FX-58H then demoted
that rule to a non-persisted review-only signal, introduced `fx58_v2`
(exact canonical URL + exact body text only), and re-ran the full
safety gate: `fx58_v2` found ZERO automatic matches against the same
real data -- a fully valid, honestly-reported success, not a failure
-- so `news_canonical_relation_vintages` is now genuinely ACTIVE
(real write-mode runs succeed and are idempotent) while still holding
zero rows, because no real automatic match currently exists. The
underlying architecture (the relation model, PIT semantics, group
derivation, the URL/body matching rules) was never in question and is
unchanged by FX-58H.

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

## FX-58H addendum (2026-10-11): `fx58_v2` -- the authorized correction

This is exactly the "future, separately-authorized follow-up" the
"Real-data finding" section above called for -- delivered as its own
reviewed story, not a quiet in-story patch.

**1. `fx58_v1` never reached real-data activation.** Every fact in
this ADR's own body above about `fx58_v1` remains true and
unmodified: it was designed, fully tested, dry-run against the real
358-item dataset, found to produce 6 confirmed false positives (plus
1 genuinely ambiguous pair) among exactly 7 proposals -- ALL via
`EXACT_HEADLINE_AND_SUMMARY` -- and consequently never wrote a single
relation row. `news_canonical_relation_vintages` held zero rows for
the entire lifetime of `fx58_v1`.

**2. Root cause, confirmed by direct inspection of the real stored
evidence**: recurring INSTITUTIONAL BOILERPLATE in a source's own
"summary" field -- Bank of Canada's unchanged-rate-decision outcome
sentence, reused verbatim across three genuinely separate monetary-
policy decisions; the Federal Reserve's own standing committee-
hearing title, reused verbatim across genuinely separate testimony
dates. Exact equality of BOTH headline AND summary does not protect
against this, because the SOURCE itself -- not FTA's own matching
logic -- is the one repeating the text.

**3. `EXACT_HEADLINE_AND_SUMMARY` is demoted to a review-only signal,
never removed from the codebase entirely.** It survives as `domain.
news_canonicalization_review.NewsCanonicalizationReviewReason.EXACT_
HEADLINE_AND_SUMMARY` -- a genuinely DIFFERENT type from `NewsCanon
icalizationMethod`, detected by a SEPARATE pure function (`detect_
review_candidate`), consulted by `CanonicalizeNewsOnce` ONLY when the
automatic matcher (`classify_candidate_pair`) already returned `None`
for that same pair -- so a pair satisfying a stronger automatic rule
is never ALSO flagged as needing review. `RecordNewsCanonicalRelation`
is NEVER called for a review candidate; it exists purely as a
reporting artifact for a future, still-unbuilt, human-audited
`MANUAL_REVIEW` workflow.

**4. `fx58_v2`'s own automatic, persistable methods are exactly
`EXACT_CANONICAL_URL` and `EXACT_BODY_TEXT`** -- `NewsCanonicaliz
ationMethod.EXACT_HEADLINE_AND_SUMMARY` was removed from that enum
entirely (not merely deprecated), and the `news_canonical_relation_
vintages.method` `CHECK` constraint was narrowed to match via a new
FORWARD migration (`3fe8c43841ee`, never editing `274aabcc57dd` in
place) -- guarded by a precheck that fails loudly if any persisted
row ever used the demoted method (none did; the precheck ran against
zero rows, exactly as expected, since `fx58_v1` never persisted
anything).

**5. No source-specific exception, blacklist, or gating was
introduced anywhere.** No Bank-of-Canada-rate-decision blacklist, no
Fed-testimony blacklist, no GOV.UK slug exception, no per-source
boilerplate dictionary, no "same source_key never matches" rule --
the GENERAL rule (`EXACT_HEADLINE_AND_SUMMARY` as independent
automatic evidence) was what the real data disproved, so the general
rule is what was fixed. `EXACT_CANONICAL_URL`/`EXACT_BODY_TEXT` both
remain fully capable of linking two different external identities
from the SAME provider, or even different providers, exactly as
before.

**6. No time-based heuristic was introduced to rehabilitate the
demoted signal.** No same-publication-day, no within-N-hours, no
same-`source_published_at`, no same-`retrieved_at` corroboration was
added anywhere -- time proximity remains explicitly not identity. The
one genuinely ambiguous real pair (the GOV.UK `--2` duplicate-slug
pair) remains review-only, with its own true disposition (genuine
republish vs. coincidental boilerplate) deliberately left unresolved
by this ADR -- that determination belongs to a future human reviewer
holding the actual pages open, not to an automated heuristic guessing
from timing alone.

**7. The underlying relation/grouping ARCHITECTURE was not touched at
all.** Every invariant this ADR's own numbered Decision list already
established (append-only vintages, FTA-decision-time availability,
pinned basis vintages, derived connected-component groups,
deterministic group keys, fail-closed contradictory graphs, `MANUAL_
REVIEW`-only `NOT_SAME_STORY`, zero `EconomicEvent` linkage, zero
network I/O) is unchanged by FX-58H. This was a matching-POLICY
correction and one concurrency-reporting bug fix (`RecordNewsCanon
icalRelation` now correctly reports `UNCHANGED` rather than `CREATED`/
`REVISION_ADDED` when a concurrent writer's identical payload lands
first -- `RelationVintageWriteResult.inserted` was previously computed
but never actually checked), never a redesign.

**8. `fx58_v2`'s own renewed dry-run against the real, unchanged
358-item dataset found ZERO automatic matches** (0 `EXACT_CANONICAL_
URL`, 0 `EXACT_BODY_TEXT`) -- a fully valid, honestly-reported
success, exactly as Section 26 of FX-58H's own spec anticipated
("Zero automatic pairs is a fully valid success"). The same 7 pairs
that previously triggered `fx58_v1`'s own false positives now
correctly surface ONLY as review-only candidates, never as automatic
relations. The first and second real write-mode runs both reported
`relations_created=0`, confirming idempotency; `news_canonical_
relation_vintages` is now genuinely ACTIVE (a real write-mode run
against it succeeds without the Section 42/43 STOP this ADR's own
original body describes) while still holding zero rows, because the
real data genuinely contains zero `fx58_v2`-automatic matches today
-- a fact about the DATA, not a limitation of the (now-corrected)
POLICY.

**9. No `NewsCanonicalRelationVintage` row required migration or
conversion.** `fx58_v1` persisted nothing; there is no historical
relation data of any kind to reinterpret, relabel, or carry forward
under `fx58_v2`.

**10. No ADR 0008 was created for this correction** -- it is a
direct, numbered addendum to this ADR, since the underlying
architecture decision was never in question; only the matching
policy and one application-layer bug were. A future ADR 0008 remains
available the day a GENUINELY new architectural question arises (e.g.
a `MANUAL_REVIEW` UI's own design, or a `fx58_v3` policy introducing a
fundamentally different kind of evidence).
