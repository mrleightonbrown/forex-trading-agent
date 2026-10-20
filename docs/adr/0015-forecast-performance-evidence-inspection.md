# ADR 0015: Forecast Performance Evidence Inspection (FX-67)

## Status

**Accepted -- code/tests complete, real-data demonstration run against
the one real, authenticated Bank of Canada performance snapshot this
codebase holds, 2026-10-19.**

## Context

FX-66/FX-66H/FX-66H.1 gave FTA the ability to *measure* and *correctly
persist* historical forecast performance, but no way for an analyst to
*independently inspect* a recorded result beyond manually reading
database rows. FX-67 adds a read-only inspection layer over that
already-recorded evidence -- it manufactures, revises, and
reinterprets nothing.

**Core principle, restated from the story itself and enforced
structurally throughout**: every displayed performance conclusion must
be explainable from immutable evidence already recorded by FX-62
through FX-66H.1. Evidence transparency is the deliverable; source
reputation scoring is explicitly not.

## Repository discovery findings

Every read this story needed already existed on an approved port,
**with one exception**: nothing could list *which* `snapshot_key`s
exist at all -- every FX-66 read method requires an already-known key.
One new port method, `ForecastPerformanceRepository.
list_distinct_snapshot_keys(*, cohort_key, limit, after_key)`, was
added (a `SELECT DISTINCT snapshot_key ...` over the existing
`forecast_performance_snapshots` table -- no new table, no migration).

A second, more significant finding surfaced only once this story's own
use cases were exercised against real Postgres: `GetForecastPerformance
Inspection` calls `ForecastEvaluationRepository.list_protocol_versions`
mid-call, sharing a session with its own other reads -- and that
PRE-EXISTING FX-65 method still called `session.commit()` after its own
`SELECT`, exactly the class of bug FX-66H.1's own F66-06 correction
fixed, but in a SIBLING repository FX-66H.1's own scope never touched
(F66-06 was scoped only to FX-66's own new methods). This recurred
across `StructuredForecastRepository.get_claim`/`list_vintages_for_claim`/
`list_production_observed_claims_as_of`/`_select_latest`,
`ForecastOutcomeRepository.latest_outcome_definition`/`list_outcome_
definition_versions`/`latest_outcome_vintage`/`list_vintages_for_outcome`,
and `SourceRegistryRepository`'s own Identity section (`get_source`/
`list_sources`/`latest_identity_vintage_for_source`/`latest_identity_
vintage_as_of`/`list_identity_vintages_for_source`) -- the SPECIFIC
method FX-67's own attribution resolution (`ResolveSourceIdentityAsOf`)
calls mid-call. This confirmed the real-Postgres transaction-isolation
test (Section 20.G) is not a formality: without this fix, the test
failed with a pending, uncommitted row becoming visible to an
independent session. The registry's own Attribution section (news-item
attribution roles, a genuinely separate concept FX-67 never calls) was
deliberately left untouched -- fixing it would be unjustified scope
creep with no FX-67 call path to justify it.

FX-61's own `apps/api/routers/market_context.py` + `view_models/`
pattern (pure JSON-dict builders over already-fetched evidence, one
data-fetch feeding both a JSON route and an HTML page) was the
presentation precedent inspected first, per Section 2. Since the story
itself says a web dashboard is not required ("Determine the smallest
useful presentation surface... A thin CLI... is sufficient"), and the
architect's own final guidance to the implementer emphasized that
exact historical evidence matters more than presentation polish, this
story introduces a new sibling presentation surface, `apps/cli/`,
mirroring `apps/api/view_models/`'s own "pure builder, already-fetched
input in" convention exactly, plus one script
(`scripts/inspect_forecast_performance.py`) mirroring `scripts/
demonstrate_forecast_performance_pilot.py`'s own CLI conventions. No
new web route, no new UI framework.

## Inspection architecture and interfaces

Eight read-only application use cases, all under `application/
use_cases/`, no new subpackage (mirrors this codebase's existing flat
layout):

- **`GetForecastPerformanceInspection`** -- the complete snapshot
  summary (Section 5): resolves the snapshot (PIT-correct, mode-gated),
  the EXACT pinned cohort/methodology/protocol versions (never
  "latest"), the target definition, the cohort's own declared
  originator identity (resolved as of the snapshot's `knowledge_
  cutoff`, never `now()`), and the full limitations set. Uses EXACT
  stored values throughout -- never recalculates MAE/accuracy.
- **`ListForecastPerformanceSnapshots`** -- bounded, paginated
  discovery of snapshot keys (the one new repository method).
- **`GetForecastPerformanceMembers`** -- paginated drill-down over a
  snapshot's own exact accepted membership, delegating per-member
  resolution to `GetForecastEvaluationInspection`.
- **`GetForecastPerformanceExclusions`** -- paginated view over a
  snapshot's own existing exclusion records; invents nothing.
- **`GetForecastEvaluationInspection`** -- traces ONE evaluation to its
  EXACT pinned forecast/outcome vintage (never current/latest), plus
  resolved originator attribution. Total over its input domain: an
  unresolvable reference returns an `UnresolvedEvidenceReference`
  diagnostic rather than raising or substituting data.
- **`GetForecastPerformanceBenchmarkInspection`** -- resolves the full
  benchmark definition (when `COMPARED`) behind the snapshot's already-
  computed `benchmark_comparison`; `BENCHMARK_UNAVAILABLE` is returned
  as the ordinary, prominent result, never an error.
- **`GetForecastPerformanceLimitations`** -- a PURE function (no I/O,
  mirrors `AssessForecastPerformanceEvidence`'s own "already-built-
  data in" convention) deriving every required limitation from
  `diagnostics`/`attribution_kind`/`benchmark_comparison`/
  `evaluation_mode`. Four STANDING disclosures are returned
  unconditionally on every call, never gated on sample size: the
  archive-completeness disclosure, the authentication-review-is-not-
  genuineness-proof disclosure, `fx66_v1`'s own no-inference disclosure,
  and the forecast-horizon-comparability disclosure (Section 11's own
  exact required sentence, reproduced verbatim as the `HORIZON_
  LIMITATION` constant).
- **`GetForecastPerformanceRevisionInspection`** -- a thin wrapper
  around FX-66H.1's own `InspectForecastPerformancePendingRevisions`,
  reused completely unchanged; never folds its result back into a
  snapshot summary.

A shared, non-use-case support module (`forecast_performance_
inspection_support.py`) holds exactly the cross-cutting pieces every
entry point needs once: `ForecastPerformanceInspectionMode`
(PRODUCTION/RETROSPECTIVE_RESEARCH, a REQUIRED keyword at every call
site -- there is no default, satisfying Section 12's "require an
unmistakable mode selection"), `resolve_snapshot_for_inspection`
(the ONE place PIT dispatch between the two FX-66 read paths happens),
`find_exact_version` (a generic "find this exact pinned version"
lookup, mirroring `BuildForecastPerformancePopulationAsOf`'s own
exact-revision-match pattern), `UnresolvedEvidenceReference`, and
`require_valid_limit`/`InvalidInspectionPageBoundsError` (Section 14's
own "invalid page bounds rejected" rule).

## Historical evidence traversal design

Every lookup resolves an EXACT `(key, revision_sequence)` pin via the
full vintage history (`list_vintages_for_*`) plus `find_exact_version`
-- never "latest." A later revision appended after a snapshot was
recorded is therefore structurally invisible to that snapshot's own
inspection, proven by both a unit test (appending a later `Structured
ForecastEvaluationVintage` revision to the fake repository) and a
real-Postgres test (appending a real later revision via `add_
evaluation_vintage`, then re-inspecting).

## Performance summary response schema

See `GetForecastPerformanceInspection`'s own `ForecastPerformance
Inspection` dataclass above. `cohort`/`methodology`/`protocol`/
`target` are all `| None` -- `None` represents an integrity gap (the
pinned version could no longer be resolved), never a fabricated
placeholder. The limitations builder was deliberately changed to take
`attribution_kind: ForecastAttributionKind | None` rather than a whole
cohort object, specifically so an unresolved cohort never forces
fabricating a placeholder `ForecastPerformanceCohortDefinition` just to
satisfy a type signature (a fabrication that was drafted, then
rejected, during implementation -- see "Deviations" below).

## Member and exclusion drill-down design

`GetForecastPerformanceMembers` orders by `evaluation_key` ascending
(already unique within one snapshot's own accepted membership, since
duplicate resolution runs before acceptance) with an explicit `limit`/
`after_key` cursor. `GetForecastPerformanceExclusions` mirrors this
exactly for the snapshot's own `exclusions` tuple, additionally
exposing the already-persisted `excluded_by_reason` summary count
(never recomputed from a possibly-partial page).

## Benchmark inspection design

`GetForecastPerformanceBenchmarkInspection` resolves the pinned
`ForecastPerformanceBenchmarkDefinition` by exact `(key, version)` only
when `comparison.status is COMPARED`; `benchmark_unresolved=True`
distinguishes "no benchmark was ever pinned" from "a benchmark was
pinned but can no longer be resolved" -- two different integrity
situations that must never be conflated.

## Evidence sufficiency presentation

Explained in detail in "Inspection architecture" above. `COMPARABLE_
SAMPLE`'s own explanation text explicitly states it does NOT mean
forecasting skill has been demonstrated and does not certify
statistical independence; `INFERENCE_SUPPORTED`'s own explanation
states its presence in a REAL result would itself be a defect (it is
never emitted by `fx66_v1`).

## Source attribution and provenance rules

A cohort's own `attribution_kind`/`originator_publisher_source_key`/
`originator_forecaster_source_key` are reused directly to construct a
`ForecastAttribution` object for cohort-level display, reusing the SAME
`resolve_originator_identity` helper the per-member path uses (one
resolution function, two callers) -- resolved as of the snapshot's own
`knowledge_cutoff`, never `now()`. `AGGREGATE_SURVEY_CONSENSUS` is
rendered as "aggregate survey consensus, published by X," never as
"X's own forecast" (proven by a dedicated unit test using "Bank of
Canada" as the publisher display name). `ANONYMOUS_RESPONDENT` never
receives an invented name (proven by a dedicated unit test).

## Production/research separation

`ForecastPerformanceInspectionMode` has no default value anywhere in
this story's own call signatures -- every entry point requires the
caller to state PRODUCTION or RETROSPECTIVE_RESEARCH explicitly.
Requesting PRODUCTION for a RETROSPECTIVE_RESEARCH-only snapshot raises
`SnapshotNotVisibleForInspectionError`, proven against both the fake
repositories and real Postgres.

## Administrative revision inspection

`GetForecastPerformanceRevisionInspection` resolves the snapshot and its
exact pinned cohort, then delegates entirely to FX-66H.1's own
`InspectForecastPerformancePendingRevisions` -- zero new revision-
diffing logic. Its result is a SEPARATE field in the rendered report/
view (`administrative_revision_inspection`), explicitly captioned as
administrative and never merged into the frozen snapshot's own fields.

## Pagination and query-bounding strategy

Every paginated use case takes a mandatory `limit` (validated by
`require_valid_limit`, rejecting non-positive values) and an optional
`after_key` cursor using the SAME unique key the result is ordered by
(`evaluation_key` for members, the exclusion's own `evaluation_key` for
exclusions, `snapshot_key` for the new listing method) -- never a
nonunique timestamp. No batched/joined multi-key repository method was
added for member drill-down; per-member sequential exact-key lookups
mirror `BuildForecastPerformancePopulationAsOf`'s own existing
per-member resolution pattern exactly, and this codebase's own real
snapshot sizes (single-digit members) do not justify a new batching
capability (Section 14's own "introduce no new caching system unless a
measured problem requires it" principle, applied here to batching too).

## Read-only transaction guarantees

Covered in detail under "Repository discovery findings" above. Proven
by a real-Postgres test (`test_read_only_inspection_lookups_do_not_
commit_unrelated_pending_writes`) inserting an uncommitted row on a
shared session, running every inspection read against it, then
confirming an independent session still cannot see it.

## Real Bank of Canada inspection example

```
$ uv run python scripts/inspect_forecast_performance.py

=== Forecast Performance Inspection: PERF:BOC-MPS-FAD-SAME-MEETING-COHORT:... ===
Mode: RETROSPECTIVE_RESEARCH  (snapshot evaluation_mode=RETROSPECTIVE_RESEARCH)
...
--- Performance metrics (exact stored values; never recalculated here) ---
MAE=0.50PERCENT  mean signed error=-0.50PERCENT  RMSE=0.50PERCENT  (n=1)

--- Evidence sufficiency ---
INSUFFICIENT_DATA: too few accepted forecasts, or too few distinct
target periods, to describe even a basic distribution of outcomes.

--- Benchmark ---
BENCHMARK_UNAVAILABLE -- no benchmark comparison applies to this snapshot.

--- Accepted members ---
  EVAL:BOC-MPS-2024Q3:...: forecast=3.75PERCENT observed=3.25PERCENT
  signed_error=-0.50PERCENT absolute_error=0.50PERCENT | originator:
  aggregate survey consensus, published by Bank of Canada | ...

--- Limitations ---
  - ...
  - Forecast horizon comparability has not been independently verified.
  - fx66_v1 supports no approved statistical-inference methodology...
```

`INSUFFICIENT_DATA` is reported as the correct, successful analytical
result for a single-evaluation population -- never as a failure state
to be explained away. The Bank of Canada survey median is attributed
as an aggregate consensus the Bank *published*, never as the Bank's own
institutional forecast. Re-run with `--mode PRODUCTION` correctly
raises `SnapshotNotVisibleForInspectionError` (this snapshot is
research-only); re-run with `--json` produces the equivalent structured
view. Verified idempotent and read-only: real-data table counts
unchanged across repeated runs.

## Synthetic inspection examples

`tests/unit/application/test_forecast_performance_inspection.py`
exercises every Section 19 fixture shape against the fake repositories
(multiple eligible/excluded forecasts, numeric and categorical
cohorts, an `AUTHENTICATED`-style `NAIVE_NUMERIC` benchmark, a missing
benchmark, later evaluation revisions, anonymous respondents, aggregate
consensus, named institutions, missing linked evidence, empty
snapshots, pagination boundaries). `tests/integration/test_forecast_
performance_inspection.py` builds one real, synthetic-but-real-Postgres
evaluation chain through the SAME production use cases real data went
through (`RecordStructuredForecast`/`RecordForecastOutcome`/
`EvaluateStructuredForecast`/`BuildForecastPerformancePopulationAsOf`/
`RecordForecastPerformanceSnapshot`) and inspects it end to end.

## Deviations and unresolved limitations

The limitations builder's own signature was changed mid-implementation
from accepting a whole `ForecastPerformanceCohortDefinition` to
accepting just `attribution_kind: ForecastAttributionKind | None`,
specifically to avoid fabricating a placeholder cohort object on an
integrity gap -- the first draft did exactly that fabrication and was
rejected before being tested.

Per-member evidence resolution remains N sequential exact-key lookups
per page rather than a single batched query; this is an accepted,
documented limitation given this codebase's own real data volumes, not
an oversight -- see "Pagination and query-bounding strategy" above.

The FX-64 horizon-field gap (no source-backed per-forecast horizon
field exists to independently verify FX-66's own declared `horizon_
category`) is NOT resolved by this story -- it is surfaced, verbatim,
on every single inspection report via `HORIZON_LIMITATION`, exactly as
required.

## Explicitly confirmed NOT done

No new forecast/outcome capture, provider adapters, evaluation
protocols, or performance calculations; no recomputed performance
snapshots or modified snapshot membership; no new statistical-
inference methods; no forecast rankings, composite source-reputation
scores, source weighting, or forecast-based trading signals; no
Decision/Risk Engine integration; no automatic trust adjustments; no
new web framework or UI dependency; no EconomicEvent linkage.

Commits: starting `32fcb35` (FX-66H.1) -> resulting FX-67 commit (see
`docs/DECISIONS.md`'s own FX-67 entry for the exact hash).

**Per this story's own explicit stop instruction**: do not begin a new
epic automatically.
