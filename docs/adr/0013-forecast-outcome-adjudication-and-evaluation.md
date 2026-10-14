# ADR 0013: Forecast Outcome Adjudication & Evaluation Protocols (FX-65)

## Status

**Accepted -- code/schema/tests complete, and a real-data pilot
evaluation ACTIVATED against one independently-verified Bank of
Canada example, 2026-10-13/14.**

## Context

FX-EPIC-09 Phase A (FX-62/62H/63/63H) gave FTA source identity,
attribution, and operational-reliability infrastructure. Phase B's
first story, FX-64/64H, gave FTA an immutable, PIT-safe structured
forecast *capture* registry -- preserving what was forecast, exactly
as forecast, without evaluating it. FX-65 is Phase B's second story:
evaluating ONE individual forecast against an independently observed
outcome under a protocol decided *before* the outcome was known. This
story explicitly does not calculate source-level forecasting skill,
reputation, or weights -- that is FX-66's own future, unauthorized
job.

## Repository discovery findings

FX-51's own `EconomicEventActualValueVintage`/`EconomicEventConsensus
Vintage` infrastructure (the economic-calendar track) was inspected
and found to hold **zero real rows** in production -- confirmed by
direct query (`economic_event_occurrences`, `..._actual_value_
vintages`, `..._consensus_vintages`, `..._release_vintages`,
`..._schedule_vintages` are all empty). Its own registry docstring
independently confirms this is a deliberate, documented scope
boundary ("FX-52A itself never populates `EconomicEventActualValue
Vintage`"), not an oversight. `macro_observation_vintages` (FX-42-47's
own policy-rate track) DOES hold real data (258 rows, CAD/EUR/GBP/USD
policy rates) -- but every row is explicitly flagged `released_at_
is_verified=False`, admitting its own `released_at` is an unverified,
conservative-bound proxy, never the source's own exact announcement
instant.

Per Section 2's own explicit instruction ("do not attach forecasts to
EconomicEvent records merely because their variable names appear
similar"; "document missing provider coverage before introducing any
outcome adapter"), FX-65 does **not** build an outcome adapter on top
of either track. `ForecastOutcomeVintage` is its own fully
self-contained, independently-verified, human-curated record --
mirroring FX-64's own real-data pilot methodology exactly, never a
join against data whose own quality this story cannot vouch for.

## Decisions

**1. Four new tables, each single-table-per-concept (NOT FX-62/64's
claim+vintage split).** `forecast_outcome_definitions`, `forecast_
outcome_vintages`, `forecast_evaluation_protocols`, `structured_
forecast_evaluation_vintages` each use `(key, version/revision_
sequence)` as their own natural unique key -- mirroring `macro_
observation_vintages`'s own simpler precedent. None of these four
concepts needs a `registered_at` distinct from version/revision 0's
own `availability` (the reason FX-62/64's identity registries DO
split), so the extra identity table would have been pure overhead.

**2. `ForecastOutcomeDefinition` reaches target semantics ONLY via
`target_key`, never by duplicating `unit`/`measurement_convention`/
`period_kind`.** `__post_init__` cross-validates `target_key` against
FX-64's own `forecast_target_registry` and that `outcome_type` is one
of the target's own `supported_forecast_types` -- Section 4's own
"do not match variables based only on display names" enforced
structurally, with exactly one place these facts can ever drift.
`required_source_series_identifier` is a free-form citation, never a
database FK onto `macro_observation_vintages` -- Decision 1's own
rationale applied here directly.

**3. Outcome-vintage resolution status draws an explicit, honest line
between "never recorded" and "recorded, but not yet as of this
instant."** `ResolveForecastOutcomeAsOf` reports `OUTCOME_UNAVAILABLE`
when `outcome_key` has never been registered at all (regardless of
`as_of`), and `NOT_YET_MATURED` when it HAS been registered but no
vintage qualifies at the requested PIT instant -- the latter is only
distinguishable in retrospect, once at least one vintage exists. This
is a deliberate definitional choice, documented explicitly because it
is not the only defensible one: FX-65 does not attempt to model "has
the real-world event happened yet" independently of what has actually
been recorded, since that would require the SAME kind of calendar-
scheduling infrastructure Section 2 told this story not to build.

**4. Evaluation admissibility is a DISTINCT, stricter gate than FX-64's
own capture eligibility -- this story's own core principle.**
`AssessForecastEvaluationAdmissibility` is pure, takes every
cross-repository input already resolved by the caller, and checks (in
order): protocol/target match, an explicit `EvidenceAuthentication
Review` for the FORECAST (required, never manufactured from FX-64's
own structural validity -- FX-64H's own boundary applied one level
up), its own corroboration reference, production-vs-research mode
compatibility, outcome resolution status, and exact target-period/unit
match against the resolved outcome. `EvidenceAuthenticationReview`
(Section 8's own narrowly-scoped new type) is the human, out-of-band
attestation Section 8 asks for -- never inferred, always explicitly
constructed by a caller who actually performed the review it
describes.

**5. The outcome-vintage selection policy is frozen on the protocol
BEFORE evaluation, never chosen to flatter a result.** `ForecastEval
uationProtocol` pins `outcome_vintage_selection_policy` (`FIRST_
RELEASE`/`LATEST_AVAILABLE_AS_OF`/`FIXED_RELEASE_VINTAGE`) and, for
the fixed case, an exact `fixed_outcome_revision_sequence` -- the SAME
inputs `ResolveForecastOutcomeAsOf` uses, so a protocol's own
evaluation question can never drift between calls.

**6. Historical determinism mirrors FX-64H's own corrected lesson,
applied to BOTH new append-only concepts from day one -- not
rediscovered the hard way a second time.** `RecordForecastOutcome`
carries the FULL FX-64H pattern (content-determinism AND provenance-
consistency, both checked over the complete historical basis) from
its very first version. `EvaluateStructuredForecast`'s own
determinism basis is the COMPLETE evaluation basis -- forecast
vintage, protocol version, outcome definition version, outcome
vintage, evaluation mode, and algorithm version -- so any genuine
data change (a new outcome revision, a new protocol version) is
AUTOMATICALLY a different basis, never compared against an earlier
one; the check instead guards against a non-deterministic bug in the
evaluation algorithm itself. The forecast's own `EvidenceAuthentication
Review` is part of the compared payload too (caught live: see
Consequences).

**7. Three distinct timelines, never conflated.** Forecast
availability (FX-64's own), outcome availability (`ForecastOutcome
Vintage.availability`), and evaluation availability (`Structured
ForecastEvaluationVintage.availability`, always caller-supplied,
never wall-clock inside domain/application logic) are three separate
fields; `GetForecastEvaluationAsOf`/`GetRetrospectiveForecastEvaluation`
mirror FX-64's own production/research read-path separation exactly
(Section 9).

**8. No admissibility result is ever persisted.** Mirrors `Structured
ForecastVintage` carrying no `eligibility` field: `StructuredForecast
EvaluationVintage` carries no `admissibility` field either, since a
non-`ADMISSIBLE` assessment is never persisted at all -- every row
that exists was `ADMISSIBLE` by construction.

## Real-data pilot example (Section 15, priority #1: Bank of Canada)

Independently verified via WebFetch against each source's own
official page, 2026-10-13:

- **Forecast**: Bank of Canada Market Participants Survey, Q3 2024
  round (published 2024-11-04; conducted 2024-09-18 to 2024-09-27; 28
  of ~30 respondents answered the December 2024 policy-rate question):
  median overnight-rate forecast for December 2024 = **3.75%**.
  <https://www.bankofcanada.ca/2024/11/market-participants-survey-third-quarter-of-2024/>
- **Outcome**: Bank of Canada Fixed Announcement Date decision,
  2024-12-11: the Bank reduced its target for the overnight rate by
  50 basis points to **3.25%**.
  <https://www.bankofcanada.ca/2024/12/fad-press-release-2024-12-11/>
- **Result**: signed error = -0.50 percentage points, absolute error
  = 0.50 percentage points -- matching Section 15's own illustrative
  figures exactly, now independently verified rather than hard-coded
  on faith.

The underlying forecast did not yet exist in FX-64's own real pilot
dataset (which covered the 2025Q1 MPS round only); `scripts/import_
pilot_forecast_evaluation.py` records it first, as `RETROSPECTIVE_
RESEARCH`, reusing the real `BANK_OF_CANADA` identity FX-62/64 already
established, then registers the outcome definition, outcome vintage,
and evaluation protocol, and finally evaluates -- confirmed idempotent
across four repeated real runs.

## Consequences

- FX-66 (historical source performance) and FX-67 remain unauthorized.
- **Two real bugs were caught live by actually running the pilot
  script against real Postgres, not merely by unit tests against
  fakes**, and both are fixed:
  1. `RecordForecastOutcomeDefinition`/`RecordForecastEvaluationProtocol`
     originally compared FULL dataclass equality (including
     `availability`) when deciding `UNCHANGED` vs. a conflict -- a
     second real run, supplying a fresh `now()`, raised a spurious
     conflict instead of reporting `UNCHANGED`. Fixed to compare only
     substantive content fields, excluding `availability`/`correction_
     reason`. Regression tests added.
  2. The pilot script itself originally set `EvidenceAuthentication
     Review.reviewed_at` to `now()` -- but the human review happened
     ONCE, on a fixed real date; a second script run's own fresh
     `now()` correctly triggered `StructuredForecastEvaluationDeterminism
     Error` (the SAME complete basis producing a payload that includes
     a different review timestamp), exposing that the script, not the
     determinism check, was wrong. Fixed by giving the review a FIXED
     `reviewed_at` constant.
- The evaluation admissibility bucket list (Section 8) is implemented
  with 8 distinct `ForecastEvaluationAdmissibility` values, including
  `INSUFFICIENT_EVIDENCE` (an authentication review present but
  carrying no independent corroboration) as a deliberately weaker
  signal than `UNVERIFIED_SOURCE` (no review at all).
- No forecast-outcome adapter, EconomicEvent linkage, aggregate source
  performance, reputation score, or trading integration of any kind
  was added.
