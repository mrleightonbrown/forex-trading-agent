# ADR 0014: Historical Forecast Performance & Statistical Evidence (FX-66)

## Status

**Accepted -- code/schema/tests complete, real-data pilot
demonstration run against the one real, authenticated FX-65
evaluation this codebase holds, 2026-10-15.**

## Context

FX-EPIC-09 Phase B's first two stories, FX-64/64H and FX-65/65H/65H.1-
65H.3, gave FTA an immutable, PIT-safe structured-forecast *capture*
registry and an individual forecast-*evaluation* registry (one
forecast vs. one outcome, under one protocol decided before the
outcome was known). Neither measures performance ACROSS multiple
evaluations. FX-66 is Phase B's third story: measuring historical
forecasting PERFORMANCE over a clearly defined, genuinely comparable
population of individual evaluations, under an explicit, versioned
methodology -- never inferring skill merely because a source has
accumulated correct predictions, and never producing a single
composite source-reputation score (FX-67's own, still-unauthorized,
future job; see "Explicitly confirmed NOT done" below).

**Core principle, stated by the architect and enforced structurally
throughout this story**: performance is a property of a clearly
defined body of comparable evidence, evaluated under an explicit
methodology -- not an intrinsic property of a source identity.

## Repository discovery findings

- **The real evaluation corpus is exactly one row**: `EVAL:BOC-MPS-
  2024Q3:CA_POLICY_RATE_LEVEL_AFTER_MEETING:AGGREGATE:boc-rate-fad-
  protocol` (FX-65's own Bank of Canada pilot). This is confirmed
  insufficient for any inferential claim, and the real-data
  demonstration (below) confirms `AssessForecastPerformanceEvidence`
  correctly reports `INSUFFICIENT_DATA` for it -- no additional real
  forecasts were fabricated to make the population appear
  statistically useful.
- **`StructuredForecastEvaluationVintage.result` (`ForecastEvaluation
  Result`) already carries the computed numeric error (`signed_error`/
  `absolute_error`) or categorical `MATCH`/`MISMATCH` outcome** --
  `CalculateForecastPerformance` reuses these directly for MAE/mean-
  signed-error/RMSE and match/mismatch/accuracy, never re-deriving
  them from scratch. Only the confusion matrix and the `NAIVE_NUMERIC`
  benchmark error need the underlying forecast's/outcome's own class/
  value, which `BuildForecastPerformancePopulationAsOf` already
  resolves and attaches to each accepted member.
- **No per-forecast structural "horizon"/lead-time field exists
  anywhere in FX-64's own `StructuredForecastVintage`.** `claim_key`
  is the only per-forecast structural distinguisher, and it is a
  caller-chosen opaque string, not a parsed lead-time. Section 4's own
  "horizon or horizon category" requirement is therefore satisfied as
  a cohort-identity/documentation dimension ONLY in `fx66_v1` --
  `horizon_category` is an exact-match-only label the cohort author
  supplies, never computed or checked against forecast data. Adding a
  genuine per-forecast horizon field would be a schema change to an
  EXISTING FX-64 table, outside this story's own explicit scope
  restriction ("do not change existing FX-64 or FX-65 historical
  tables without an explicit architectural justification") -- a
  limitation surfaced here explicitly, not papered over.
- **FX-65 never persists an inadmissible evaluation attempt** --
  `EvaluateStructuredForecast` rejects before reaching its own
  repository. A "missing or unresolved outcome" exclusion (Section 6)
  is therefore currently unreachable by construction; the domain enum
  value exists for forward compatibility (documented explicitly in
  its own docstring) but is never emitted by `fx66_v1`.
- **`FX-65H.2`'s own durable `outcome_key` <-> measurement-identity
  binding is reused as the "target event" identity throughout this
  story** -- "unique target events" (Section 7/8) is simply the count
  of distinct `outcome_key` among accepted cohort members, since one
  `outcome_key` is bijective with one measurement identity by FX-65H.2's
  own invariant. No new event-identity concept was invented.

## Decisions

**1. Cohort/methodology/benchmark are three separate append-only
single-table-per-concept registries (`forecast_performance_cohorts`/
`_methodologies`/`_benchmarks`), mirroring `forecast_outcome_
definitions`'s own simpler precedent** -- none of the three needs a
`registered_at` distinct from version 0's own `availability`. A
cohort owns the comparability/eligibility DIMENSIONS (Section 4);
a methodology owns HOW a pinned cohort's own population is calculated
and interpreted (benchmark pin, missing-data policy, `algorithm_
version`); a benchmark owns ONE of three admissible comparison shapes.
Separating cohort from methodology means the SAME cohort evaluated
under two methodology versions produces two separately identifiable
analyses (Section 14's own explicit requirement), without re-defining
the population itself.

**2. Originator identity reuses FX-64's own `ForecastAttribution`
fields directly** (`attribution_kind` + `originator_publisher_
source_key` + an optional `originator_forecaster_source_key`,
required iff `NAMED_INSTITUTION`) -- Section 5's own explicit "use
FX-62/64's existing originator semantics" instruction, satisfied
without inventing a new identity concept. An aggregate survey
consensus's own cohort is identified by its PUBLISHER, never
conflated with an individual forecaster (Section 5's own Bank-of-
Canada example).

**3. Benchmarks are one of three closed kinds, all reusing EXISTING
evidence, never fabricating a comparison**: `AUTHENTICATED_SERIES`
reuses ANOTHER already-registered cohort's own real evaluations,
paired by shared `outcome_key`; `NAIVE_CATEGORICAL` is a fixed,
declared predicted class; `NAIVE_NUMERIC` is a fixed, declared
reference value with its own documented evidence. A dynamically-
computed "no-change from the prior observed value" benchmark was
considered and explicitly REJECTED for `fx66_v1` -- this codebase has
no established historical-input pipeline for it yet, and Section 11
itself permits `NAIVE_NUMERIC` "only where its required inputs and
historical availability are established." `BENCHMARK_UNAVAILABLE` is
a first-class, expected result, never an error.

**4. `BuildForecastPerformancePopulationAsOf` fetches candidates
UNBOUNDED by any PIT instant, then applies an explicit, caller-side
`availability <= as_of` filter itself** -- mirroring `latest_outcome_
vintage`'s own "administrative, unbounded; the caller applies its own
PIT check" convention, specifically so a too-new evaluation is
classified `NOT_YET_AVAILABLE` in the audit trail (Section 6's own
"an excluded evaluation must remain visible in the audit trail" rule)
rather than silently never being fetched at all.

**5. Duplicate/overlap resolution (Section 7) runs LAST, grouped by
shared `outcome_key`, keeping the member with the earliest forecast-
issue instant (`original_publication_at`, falling back to
`availability` only when absent) under the ONE implemented policy,
`EARLIEST_QUALIFYING_ISSUE`** -- a `FIXED_LEAD_TIME` policy is named
in the domain enum's own docstring as deliberately deferred until a
real population needs it (Section 7 itself only requires "an explicit
choice," not every conceivable one).

**6. Sample-adequacy classification is a FIXED, hardcoded, documented
rule** (`INSUFFICIENT_DATA` below 5 accepted members; `DESCRIPTIVE_
ONLY` for `RETROSPECTIVE_RESEARCH` regardless of size, or for 5-19
accepted `PRODUCTION_OBSERVED` members; `COMPARABLE_SAMPLE` for 20-29;
`INFERENCE_SUPPORTED` for 30+ `PRODUCTION_OBSERVED` members) -- never
a configurable methodology parameter a caller could tune to flatter a
result (Section 8's own explicit "do not set arbitrary significance
thresholds merely to produce PASS results"). Changing these numbers
requires a new `algorithm_version`, the SAME audit mechanism every
other calculation-logic change in this codebase uses.

**7. `RecordForecastPerformanceSnapshot` mirrors `EvaluateStructured
Forecast`'s own basis/payload-split full-history determinism exactly**
-- basis = `(cohort_key, cohort_version_sequence, methodology_key,
methodology_version_sequence, evaluation_mode, knowledge_cutoff,
algorithm_version)`; payload = the snapshot's own COMPLETE evidence
basis (exact membership, exact exclusions, whichever summary shape
applies, the benchmark comparison, and full sample diagnostics) --
never only a headline metric (Section 16's own explicit rule).

**8. Snapshot membership and exclusions are proper relational child
tables** (`forecast_performance_snapshot_members`/`_exclusions`), not
JSON blobs, satisfying Section 18's own "should not be the only
representation of exact evidence membership when relational
constraints are needed" requirement; the multi-row write (main row +
member rows + exclusion rows) is genuinely atomic (one uncommitted
transaction, committed together, rolled back together on conflict).
`confusion_counts`/`realized_class_distribution` remain `JSONB` on the
main row -- small, non-relationally-critical diagnostics nothing ever
queries into independently, mirroring `NewsSemanticAnnotationVintage
Row`'s own established `JSONB` convention. `excluded_by_reason` is NOT
persisted at all -- fully reconstructable via `COUNT(*) GROUP BY
reason` over the exclusions child table on read, never duplicated.

**9. One purely additive repository-port extension**: `ForecastEvaluationRepository.
list_latest_evaluations_for_protocol` -- the one place this story
touches an EXISTING FX-65 contract, and only by ADDING a new read
method (no existing method's own behavior changes), mirroring FX-65H.2's
own precedent for extending an existing port additively.

## Mandatory tests verification

62 new tests (13 domain construction/validation, 21 synthetic-fixture
pipeline tests covering cohort construction/membership, duplicate/
overlap resolution, numeric metrics, categorical metrics, and all
three benchmark kinds, 13 Define*-use-case tests, 8 `RecordForecast
PerformanceSnapshot` determinism/idempotency/PIT tests, 7 real-
Postgres integration tests), plus 38 pre-existing architecture-
boundary contract tests auto-parametrized over the new domain/
application files (all passing, confirming no forbidden imports and
no `os.environ` access anywhere in the new domain/application code).
Full suite: 3244 passed (up from 3144). `ruff`/`ruff format`/`mypy`/
`pre-commit` all clean.

## Real pilot (Dataset A) and real-data integrity

`scripts/demonstrate_forecast_performance_pilot.py` runs the full
pipeline against the one real BoC evaluation: `AssessForecastPerformance
Evidence` correctly reports `INSUFFICIENT_DATA` (1 accepted member, 1
unique target event), `CalculateForecastPerformance` reproduces the
already-known MAE/mean-signed-error/RMSE of exactly 0.50 percentage
points, `BENCHMARK_UNAVAILABLE` is reported honestly (no benchmark
pinned), and the explicit `EVIDENCE_INSUFFICIENT_FOR_SKILL_INFERENCE`
statement is printed -- no claim of demonstrated forecasting skill.
Re-run twice (CREATED then UNCHANGED): fully idempotent once a FIXED
`knowledge_cutoff` constant is used (a fresh `now()` there would mint
a genuinely new determinism basis on every run, by this story's own
design -- the SAME "fix any value meant to represent a stable point"
lesson this epic has already learned twice, applied here a third
time). All FX-62 through FX-65H.3 real-data counts (394/358/12/400/34/
6/7/1/1/1/1/1) are unchanged; the new FX-66 tables hold exactly 1
cohort, 1 methodology, 0 benchmarks, 1 snapshot, 1 member, 0
exclusions.

## Explicitly confirmed NOT done

No single composite source-reputation score; no source ranking,
automatic weighting, or source selection for trading; no Decision/Risk
Engine changes; no new forecast or outcome adapters; no change to
FX-64 forecast-capture semantics, authentication semantics, evaluation
metrics, or FX-65H.2/H.3 outcome-identity-binding mechanics; no change
to any existing FX-62/64/65 historical table. FX-67 (source-level
performance inspection/dashboard) remains unauthorized.

Commits: starting `b4bfb32` (FX-65H.3) -> resulting FX-66 commit (see
`docs/DECISIONS.md`'s own FX-66 entry for the exact hash).
