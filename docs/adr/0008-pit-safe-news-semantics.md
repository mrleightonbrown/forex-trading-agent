# ADR 0008: PIT-Safe News Relevance, Entities & Topics (FX-59)

## Status

**Accepted -- code/schema/tests complete, and real-data activation
COMPLETE, 2026-10-12. A narrow recording-invariant correction (FX-59H,
2026-10-12) is recorded in this ADR's own addendum at the end of this
document -- the classifier policy, schema, and real annotations below
are otherwise unchanged by it.** The required pre-persistence dry-run
safety gate (Section 79/80 of FX-59's own spec) found 2 multi-currency
classifications and 17 explicit-foreign-institution classifications
against the real, already-ingested 358-item dataset; every one was
directly inspected against the underlying stored text and confirmed
to be a genuine, correct textual fact -- zero false positives, zero
alias collisions, zero wrong topic rules, zero rule corrections
needed. The first real write-mode run created exactly 358 semantic
annotations (one per item); the second, immediately-repeated run
reported `annotations_created=0`, confirming idempotency.

## Context

FX-56/FX-57 gave FTA six independent, source-native news ingestion
pipelines; FX-58/FX-58H added a derived layer answering "do two
different source items represent the SAME underlying story?" Neither
layer answers a different, equally necessary question: "what is this
ONE piece of evidence actually ABOUT?" -- which macro subject(s),
which institutions/jurisdictions, and which currencies does FTA have
explicit textual or structural evidence this item is relevant to?

FX-59 answers exactly that question, as a second DERIVED evidence
layer, strictly at the `NewsItem` level -- never against a canonical
group, and never altering any FX-56/57/58 fact.

## Decisions

**1. Semantic annotations are a separate, derived layer from source-
native news.** `NewsSemanticAnnotationVintage` (`domain.news_
semantic_annotation_vintage`) is a NEW, append-only table (`news_
semantic_annotation_vintages`, migration `4b2621787a37`) -- no
existing `news_*` table is touched, mutated, or gains a new column.
Classification never merges `NewsItem`s, repoints source mappings, or
asserts anything about identity; it is pure "what is this evidence
about," orthogonal to "is this the same story as that other item."

**2. Annotations are append-only PIT vintages, mirroring FX-56/58's
own established shape exactly.** `(news_item_key, revision_sequence)`
is the natural identity; no application code path anywhere issues an
`UPDATE` against this table. A correction (a new basis revision, or a
new `algorithm_version`) is always a NEW, higher-revision row.

**3. `availability` is ALWAYS the instant FTA actually RAN and
RECORDED a classification -- never a source timestamp, never the
basis `NewsItemVintage`'s own availability.** `ClassifyNewsOnce`
captures `run_at` exactly once per run, via an injected clock, and
uses that same instant for every annotation the run produces --
identical discipline to `CanonicalizeNewsOnce`'s own `run_at` capture.

**4. The exact basis `NewsItemVintage` is pinned, never copied.**
`basis_news_item_revision_sequence` carries a genuine composite
foreign key into `news_item_vintages(news_item_key, revision_
sequence)` -- an auditor can always recover exactly which headline/
summary/body/content-type/channel was classified, without this table
ever duplicating that content.

**5. A stale annotation can never masquerade as current semantics.**
`GetNewsSemanticStateAsOf` distinguishes three states as of a
requested instant: `CURRENT` (the latest annotation's own basis
revision equals the item's current evidence-eligible vintage as of
that instant), `STALE` (an annotation exists, but its basis no longer
matches -- e.g. the source produced a new revision the classifier has
not yet re-run against), and `UNCLASSIFIED` (no annotation at all).
Pinned by a dedicated real-Postgres worked example (`09:00` rev0
available; `09:05` classified, CURRENT; `09:20` rev1 becomes
available; `09:25` STALE; `09:30` reclassified against rev1; `09:35`
CURRENT again; a historical query before `09:20` remains CURRENT for
that instant -- no destructive rewrite).

**6. `fx59_v1` is deterministic and rule-based -- no LLM, no
embeddings, no statistical NER, no cloud NLP, no zero-shot
classification, no fuzzy semantic similarity, no web search, no
external news metadata.** `classify_news_semantics` (`domain.news_
semantic_classifying`) is a pure function: curated source profiles
plus deterministic, phrase/token-boundary-safe text rules
(`domain.news_semantic_text_matching.find_matched_phrases`) only. This
gives a measurable, fully auditable baseline before any future story
considers a richer semantic model (which would ship as `fx59_v2`,
never retroactively reinterpreting what `fx59_v1` meant).

**7. A curated source profile establishes publisher institution,
jurisdiction, and primary currency -- structurally, never inferred
from an item's own text.** All six adopted sources (FED/ECB/BOE/
GOVUK_HMT/STATCAN/BOC) have an explicit `NewsSemanticSourceProfile`.
An evidence-eligible item from any OTHER `source_key` fails closed
(`UnsupportedNewsSemanticSourceError`) -- `ClassifyNewsOnce` never
silently emits an entity-less, currency-relevance-less annotation for
a source nobody has reviewed; it classifies EVERY candidate in memory
first and only then records, so one unsupported source leaves zero
annotations half-written.

**8. Foreign currency relevance requires EXPLICIT currency or mapped-
institution text evidence -- a bare jurisdiction mention is
insufficient on its own.** Every item gets its source's own primary
currency (`SOURCE_JURISDICTION`, always present). A SECOND currency
is added only via an explicit currency alias match
(`EXPLICIT_CURRENCY_MENTION`, e.g. "sterling," "U.S. dollar" -- never
bare "dollar") or an explicit mention of an institution mapped to a
different currency (`EXPLICIT_INSTITUTION_MENTION`, e.g. a Bank of
Canada item explicitly naming the European Central Bank). A bare
jurisdiction mention (e.g. "Canada," "United States") never adds
currency relevance by itself -- this deliberately limits noise
(Section 31 of the story's own spec).

**9. Topics are multi-label categorical evidence, with no score.** A
closed v1 taxonomy of nine macro categories (`domain.news_topic.
NewsTopic`); a story may match zero, one, or several topics
simultaneously. No `OTHER` catch-all exists -- zero topics is itself a
valid, meaningful result (246 of 358 real items matched none, which
is a correct reflection of this story's own deliberately conservative
taxonomy, not a gap to be papered over). Publisher identity alone
NEVER implies a topic (e.g. HM Treasury's own items are not
automatically `FISCAL_POLICY`) -- text evidence is always required.

**10. No sentiment/stance, and no importance/impact score, anywhere
in this layer.** `NewsSemanticClassification`'s surface is exactly
`entities`/`topics`/`currency_relevance` -- no hawkish/dovish,
bullish/bearish, positive/negative, or 0-100 rank field exists. FX-59
identifies subject matter and relevance only; any future market-
direction interpretation is explicitly out of scope here.

**11. Item-level semantics remain separate from canonical groups.**
`GetNewsSemanticStateAsOf`/`GetNewsSemanticStatesAsOf` operate on
`news_item_key`, never a canonical-group key -- if two source-native
items later become `SAME_STORY` under FX-58, their own FX-59
histories remain completely untouched. Deriving canonical groups and
aggregating member semantics together is explicitly FX-60's own job,
not preempted here.

**12. Pair-specific interpretation belongs to FX-60, not here.** FX-59
stops at item-level currency relevance; it never constructs a
currency-pair-specific evidence bundle, snapshot, or relevance score
(e.g. no "EUR/USD news snapshot").

## Real-data finding

The required pre-persistence dry-run safety gate (`scripts/classify_
news.py --dry-run`, run against the real, live 358-item dev database)
reported 2 multi-currency classifications and 17 explicit-foreign-
institution classifications. Every one was directly inspected against
the item's own stored summary/headline text:

- Both multi-currency items are BoE speeches: one explicitly discusses
  "stablecoins and US dollar dominance" (GBP + USD, correct); one was
  "Given at ECB Sintra Forum" (GBP + EUR, correct).
- All 17 foreign-institution mentions were spot-checked; the one that
  initially looked surprising -- a Statistics Canada "Sector-based
  Producer Price Indexes" release mentioning `BANK_OF_CANADA` -- was
  confirmed via direct SQL inspection to be a genuine textual fact
  ("...using a methodology developed by the Bank of Canada").

**Zero false positives, zero alias collisions, zero wrong topic
rules were found.** No source-specific exception, no source-key
gating, and no rule weakening/strengthening was applied anywhere --
the gate passed on the FIRST real dry-run, with the general rules
exactly as designed. This is reported honestly as a successful,
inspected gate, not assumed.

## Consequences

- `news_semantic_annotation_vintages` is genuinely ACTIVE: the first
  real write-mode run created 358 annotations (one per genuine
  source-native item); the second, immediately-repeated run reported
  `annotations_created=0`, confirming idempotency.
- Topic distribution across the real dataset: `MONETARY_POLICY` 39,
  `LABOUR_EMPLOYMENT` 17, `INFLATION_PRICES` 15, `GROWTH_ACTIVITY` 13,
  `INTERNATIONAL_TRADE` 11, `FINANCIAL_STABILITY` 11, `FISCAL_POLICY`
  10, `EXCHANGE_RATES` 4, `BANKING_REGULATION` 4; 246 items matched no
  topic (a correct reflection of the deliberately small taxonomy, not
  a defect); 8 items matched more than one topic.
- Currency relevance distribution: GBP 170, CAD 121, USD 46, EUR 23
  (reflecting each source's own primary currency, plus the 2
  multi-currency items above).
- FX-60 (pair-specific news evidence snapshot) is now explicitly
  cleared to begin, pending separate authorization -- it may reuse
  `GetNewsSemanticStatesAsOf`'s batch PIT query directly, per this
  ADR's own Decision 11/12.

## FX-59H addendum (2026-10-12): determinism enforced across an
item's FULL history, not merely its latest row

**Finding.** FX-59's own original `RecordNewsSemanticAnnotation`
checked Decision 9's own determinism invariant (`(basis_news_item_
revision_sequence, algorithm_version)` -> at most one classification
payload) ONLY against the item's currently-LATEST annotation. This
missed a real gap: if an OLDER `algorithm_version` becomes current
again later (e.g. `fx59_v1` -> `fx59_v2` -> `fx59_v1`), the item's own
latest row at that third instant is the `fx59_v2` one, not the
`fx59_v1` one -- so a latest-only check could never compare the new
`fx59_v1` output against the OLDER, already-stored `fx59_v1` output,
and a genuinely non-deterministic classifier output could have slipped
past undetected.

**Correction.** The invariant is now checked against the item's
ENTIRE stored annotation history (via the existing `list_annotation_
vintages_for_item`, no new repository method, no schema change): for
every historical row sharing the SAME `(basis_news_item_revision_
sequence, algorithm_version)` pair as the incoming classification, its
own stored payload must equal the incoming one, or `NewsSemantic
DeterminismError` is raised -- regardless of whether that historical
row is currently the item's own latest. PIT ordering is still checked
strictly FIRST, unconditionally, before this historical check, so an
out-of-order `availability` is rejected before any determinism
comparison runs. The basis-revision dimension remains part of the
deterministic key exactly as before (Decision 6/9) -- two different
basis revisions under the same algorithm are never compared against
each other. No unique database constraint was added on `(news_item_
key, basis_news_item_revision_sequence, algorithm_version)`, since a
later revision genuinely reusing an earlier basis+algorithm pair (the
`fx59_v1` -> `fx59_v2` -> `fx59_v1` sequence) is a legitimate
`REVISION_ADDED`, never a once-only identity.

**Scope.** This is a recording-invariant fix only -- no classifier
policy, source profile, alias registry, topic rule, or text-matching
behavior changed; `algorithm_version` remains `fx59_v1`; no new real
annotation revision was required (the dry-run and a real write-mode
run against the unchanged 358-item dataset both reported `created=0,
revisions_added=0, unchanged=358`, confirming the correction altered
no existing decision). No migration was needed or made.
