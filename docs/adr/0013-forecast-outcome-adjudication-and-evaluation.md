# ADR 0013: Forecast Outcome Adjudication & Evaluation Protocols (FX-65)

## Status

**Accepted -- code/schema/tests complete, and a real-data pilot
evaluation ACTIVATED against one independently-verified Bank of
Canada example, 2026-10-13/14. FX-65H (evaluation basis and PIT
integrity hardening) and FX-65H.1 (authoritative outcome identity
binding) closed the same cycle -- see this ADR's own addenda below.**

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

## FX-65H addendum (2026-10-14): evaluation basis and PIT integrity hardening

Independent architectural review of FX-65 (mandatory per Section 20's
own closing instruction) surfaced three findings, all closed as
corrective implementation only -- no schema/migration change, no
change to numeric/categorical computation, no change to append-only
history or FX-64's own approved semantics.

**H1 -- the outcome is now OBTAINED, never merely TRUSTED.** FX-65's
own original design let a caller supply a pre-computed `ForecastOutcome
ResolutionResult` directly to `EvaluateStructuredForecast`, which
trusted it whenever its status was `OUTCOME_AVAILABLE` -- nothing
verified that the supplied vintage was actually what the protocol's
own `outcome_vintage_selection_policy` would have selected, nor that
it was captured under the protocol's own pinned outcome definition.
Fixed by making `EvaluateStructuredForecast` resolve the outcome
INTERNALLY: the caller now supplies only `outcome_key`, and this use
case calls the SAME authoritative `ResolveForecastOutcomeAsOf` itself
(reusing the existing resolver, never a second independent selection
algorithm), using the protocol's own policy/pinned-revision fields and
the evaluation's own `availability` as the PIT bound. This makes
cherry-picking an outcome vintage structurally impossible rather than
merely detectable after the fact -- there is no longer a parameter
through which a caller COULD supply a mismatched resolution. The
resolver itself does not filter by definition, so `AssessForecastEval
uationAdmissibility` additionally cross-checks the resolved outcome's
own `definition_key`/`definition_version_sequence` against the
protocol's own pinned definition, folded into the existing `PROTOCOL_
MISMATCH` verdict (the same "this does not match what the protocol
requires" family, never a new category). This IS an incompatible
change to `EvaluateStructuredForecast`'s own public signature
(`outcome_resolution` removed, `outcome_repository` and `outcome_key`
added) -- explicitly justified: the removed parameter's entire
purpose was the exact trust boundary this finding identified as
broken, so closing it structurally is more defensible than adding
verification logic around a parameter designed to be bypassed.
`algorithm_version` stays `fx65_v1` -- this is a safety/orchestration
fix, not a change to how a given (forecast, outcome) pair is
interpreted into a result.

**H2 -- every evaluation input's own FTA-knowledge timestamp is now
enforced.** Nothing previously checked that the evaluation's own
recorded `availability` was no earlier than the forecast vintage, the
protocol version, the outcome vintage, the outcome definition version,
or either authentication review's own `reviewed_at`. Fixed by adding
this check to `AssessForecastEvaluationAdmissibility` (new verdict:
`INPUT_NOT_YET_AVAILABLE`), comparing exclusively against each input's
own `availability`/`reviewed_at` field -- never a publisher-declared
release timestamp (Section 10's own three-timelines discipline,
extended to a fourth and fifth: the outcome definition's own
availability and both authentication reviews' own `reviewed_at`).
`EvaluateStructuredForecast` fetches the specific pinned outcome-
definition version via the ALREADY-APPROVED `list_outcome_definition_
versions` method (no new repository interface) to make this check
possible.

**H3 -- production evaluation now requires BOTH sides to be
production-observed.** The original check only verified the
FORECAST's own `provenance_mode` against `PRODUCTION_OBSERVED`
evaluations; the OUTCOME side was unchecked, permitting an implicit
promotion of retrospective outcome evidence into a production
evaluation. Fixed with a symmetric check on the outcome vintage,
reusing the existing `RESEARCH_ONLY` verdict (no new category).
Retrospective-research evaluations continue to accept either
provenance mode for both inputs, unchanged.

**Verification**: 15 new/updated test files' worth of coverage across
all 15 of the story's own mandatory regression scenarios (correct-
case acceptance; wrong definition key/version; FIRST_RELEASE/FIXED_
RELEASE_VINTAGE cherry-pick attempts, now structurally impossible;
future outcome/protocol/forecast/review inputs; retrospective-outcome-
in-production; correctly-authenticated retrospective evaluation;
historical-evaluation-unchanged-after-later-outcome-revision; rejected-
evaluation-writes-nothing; concurrent/idempotent behavior), plus real-
PostgreSQL integration coverage for the incorrect-outcome and FK cases.
Full suite: 3107 passed (up from 3092). `ruff`/`ruff format`/`mypy`/
`pre-commit` all clean. No migration. The real Bank of Canada pilot
evaluation was re-run against real Postgres and continues to report
`UNCHANGED` with `signed_error=-0.50`/`absolute_error=0.50` -- the
exact result from before this hardening, now additionally proven to
have survived structural re-verification of its own outcome
selection, definition pinning, and input-availability ordering.

Commits: starting `f8c7ac5` (FX-65) -> resulting FX-65H commit (see
`docs/DECISIONS.md`'s own FX-65H entry for the exact hash).

## FX-65H.1 addendum (2026-10-14): authoritative outcome identity binding

FX-65H's own H1 fix closed the "caller supplies a mismatched outcome
resolution" hole by making `EvaluateStructuredForecast` resolve the
outcome itself via the protocol's own pinned policy. One ambiguity
remained: the caller still chose `outcome_key` freely, and NOTHING in
the data model prevented two genuinely DIFFERENT `outcome_key`s from
sharing the identical `(definition_key, target_period, unit)` identity
-- confirmed by direct inspection of `forecast_outcome_vintages`'s own
schema (the ONLY uniqueness constraint is `(outcome_key, revision_
sequence)`; nothing ties `outcome_key` to what it actually measures).
Had this gone unaddressed, a caller could obtain different evaluation
results merely by choosing a different, equally "compatible"
`outcome_key` for what is really the same real-world outcome.

**Chosen approach (Section 2's own option A, applied at the
narrowest effective point): enforce uniqueness at WRITE time, in
`RecordForecastOutcome`, rather than deriving `outcome_key`
automatically.** A new repository method, `list_outcome_vintages_for_
definition(definition_key)`, lets `RecordForecastOutcome` check, on
every registration, whether any OTHER `outcome_key` already holds the
identical `(definition_key, target_period, outcome_type, unit)`
identity; if so, the new `ForecastOutcomeIdentityConflictError` is
raised and nothing is written. The FIRST `outcome_key` ever registered
for a given identity becomes its sole legitimate one, permanently --
every later attempt to introduce a DIFFERENT key for that same
identity is refused at the source, before an evaluation could ever
reach it.

**Why this approach over deriving `outcome_key` from `(definition_
key, target_period)` automatically**: a deterministically-derived key
would have required renaming the EXISTING real pilot row's own
`outcome_key` (`BOC-RATE-DECISION-2024-12-11`) to match a new
canonical string format, cascading into the dependent `structured_
forecast_evaluation_vintages.outcome_key` FK column too -- a
migration carrying real rename risk for no additional safety over the
simpler write-time uniqueness guard, which achieves the IDENTICAL
invariant (at most one legitimate `outcome_key` per identity) without
touching a single existing row. This is "the smallest solution
consistent with the existing data model" the story's own Section 2
asked for.

**Why enforcement at WRITE time, not evaluation time**: once
write-time uniqueness holds, there is structurally nothing left TO
substitute at evaluation time -- a caller supplying ANY `outcome_key`
either reaches the one-and-only legitimate identity for that
definition+period, or reaches nothing at all (a different definition/
period entirely, already rejected by FX-65H's own H1 cross-check).
Adding a second, redundant check at evaluation time would duplicate
logic without adding protection, given all production writes go
through this one use case.

**No schema change.** The new repository method is a plain `SELECT
... WHERE definition_key = ...` against the already-existing column
-- no new index, no new constraint, no migration. A concurrent race
between two DIFFERENT, genuinely NEW `outcome_key`s for the same
identity remains theoretically possible (the same class of TOCTOU
window already accepted elsewhere in this codebase, e.g. `Forecast
OutcomeDefinition`'s own sequential-version check) -- not closed here,
consistent with this story's own "smallest solution" instruction and
the low-volume, curated nature of outcome registration.

**Verification**: 5 new tests (4 unit against the fake repository, 1
real-PostgreSQL integration test proving the conflict is rejected and
writes nothing). Full suite: 3112 passed (up from 3107). `ruff`/`ruff
format`/`mypy`/`pre-commit` all clean. No migration. The real Bank of
Canada pilot evaluation was re-run against real Postgres four times
(including `--dry-run`) and continues to report `UNCHANGED` with
`signed_error=-0.50`/`absolute_error=0.50`, confirming the single
existing real `outcome_key` remains its own identity's sole
legitimate holder, untouched by this change.

Commits: starting `6108ce2` (FX-65H) -> resulting FX-65H.1 commit
(see `docs/DECISIONS.md`'s own FX-65H.1 entry for the exact hash).

## FX-65H.2 addendum (2026-10-14): durable outcome identity integrity

FX-65H.1's own write-time uniqueness check had two gaps, both named
explicitly in this story's own spec: (1) a plain `SELECT ... WHERE
definition_key = ...` followed by an `INSERT` is a read-then-decide
sequence, not atomic -- two concurrent PostgreSQL transactions could
both pass the check before either commits, each believing itself the
sole legitimate holder of an identity; (2) the check only ever
compared the identity against OTHER outcome_keys' own vintages for
the SAME `definition_key` -- it never verified that an EXISTING
`outcome_key`'s own new vintage retained the SAME identity it first
registered, so one key could silently drift its own target_period,
outcome_type, or unit across revisions with nothing to stop it.

**Existing-data integrity findings (H3, pre-migration)**: before
writing the migration, `forecast_outcome_vintages` was inspected
directly against both conflict shapes this story names -- two
different `outcome_key`s sharing one identity, and one `outcome_key`
spanning more than one identity. Neither existed: the real dataset
holds exactly one `outcome_key`
(`BOC-RATE-DECISION-2024-12-11`), making this migration's own H3
pre-flight check (below) a precaution for future data, not a
remediation of anything found.

**Chosen atomic mechanism**: a new table, `forecast_outcome_identity_
bindings`, with TWO unique constraints -- `(definition_key, target_
period_key, outcome_type, unit)` (H1: one identity, at most one
owning `outcome_key`) and `(outcome_key)` alone (H2: one `outcome_
key`, exactly one identity, ever). `target_period` is flattened to one
comparable string via a new pure function, `domain.forecast_outcome_
identity.canonical_target_period_key`, because the period's own
nullable per-kind columns would otherwise defeat the composite unique
constraint under Postgres's NULL-is-distinct-from-NULL semantics; a
sentinel string (`__NO_UNIT__`) plays the identical role for `unit`,
which is itself nullable for `CATEGORICAL_EVENT` outcomes.

**PostgreSQL uniqueness and transaction guarantees**: `RecordForecast
Outcome` claims a brand-new `outcome_key`'s own identity via ONE
atomic repository method, `claim_outcome_identity_and_add_first_
vintage`, mirroring FX-62/64's own established atomic-first-
registration pattern exactly -- the binding row is inserted first
with `ON CONFLICT DO NOTHING` and no commit; a conflict on EITHER
unique constraint rolls back immediately with NOTHING written, not
even the vintage; success inserts the vintage in the SAME uncommitted
transaction and commits both together. Postgres's own unique-
constraint enforcement at `INSERT` time -- not a read followed by a
decision -- is what makes two concurrent claims for the same identity
under different keys structurally unable to both succeed, closing the
exact gap FX-65H.1's own version left open.

**Same-key identity immutability contract (H2)**: a REVISION of an
already-bound `outcome_key` never re-claims the binding table (its
own identity is already durably fixed) -- `RecordForecastOutcome`
instead performs one plain read, `get_identity_binding_for_key`, and
raises the new `ForecastOutcomeIdentityImmutabilityError` if the
incoming submission's own `(definition_key, target_period, outcome_
type, unit)` differs from what that key first registered. A revision
sharing the IDENTICAL identity (a corrected value, new evidence) is
unaffected -- only a change to one of those four fields is rejected.

**Migration/backfill results**: migration `80877afdbe75` ran its own
H3 pre-flight check (confirmed no conflicts, as above), created the
table with both unique constraints plus five `CHECK` constraints, and
backfilled one row per distinct `outcome_key` already present using
SQL that mirrors `canonical_target_period_key` byte-for-byte (verified
directly against the one real row: `'POLICY_MEETING:BOC-2024-12-11'`
from both the Python function and the migration's own SQL `CASE`
expression). No existing `outcome_key` was renamed; `forecast_outcome_
vintages` itself was neither touched nor mutated. `downgrade()` is
guarded, mirroring every prior FX-56+ migration's own precedent --
once the table holds a row, dropping it would silently discard the
durable exclusivity record.

**Verification**: 29 unit tests (10 new domain tests for `canonical_
target_period_key`/`ForecastOutcomeIdentityBinding`, 19 for `Record
ForecastOutcome` including 8 new H2/dry-run cases) plus 14 real-
Postgres integration tests (10 existing plus 4 new: two DIFFERENT
outcome_keys racing for the same identity under two independent
Postgres sessions -- exactly one winner, the loser leaves no binding
or vintage; a real-Postgres H2 immutability rejection; a direct
repository-level test proving a lost identity claim leaves neither a
binding row nor its own vintage; and a regression guard confirming
the real backfilled Bank of Canada binding matches the canonical key
computed at runtime). Full suite: 3136 passed. `ruff`/`ruff
format`/`mypy`/`pre-commit` all clean. The real Bank of Canada pilot
was re-run against real Postgres (including `--dry-run`) and continues
to report `UNCHANGED` throughout, with the evaluation's own
`signed_error=-0.50`/`absolute_error=0.50` unchanged and the retained
`outcome_key=BOC-RATE-DECISION-2024-12-11` now durably bound in the
new table. Real-data row counts across all twelve relevant tables
(394 news items, 358 semantic annotations, 12 intelligence sources,
400 attribution vintages, 34 operational observations, 6 forecast
claims, 7 forecast vintages, 1 outcome definition, 1 outcome vintage,
1 identity binding, 1 protocol, 1 evaluation) match the FX-65H.1
baseline exactly, plus the one new binding row.

Commits: starting `6f8257f` (FX-65H.1) -> resulting FX-65H.2 commit
(see `docs/DECISIONS.md`'s own FX-65H.2 entry for the exact hash).
