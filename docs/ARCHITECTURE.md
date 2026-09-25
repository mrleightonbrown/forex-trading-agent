# Architecture

Python modular monolith. Dependencies flow one way:

```
apps -> application -> domain
```

`infrastructure` implements ports defined by `application`; nothing depends
on `infrastructure`.

```
src/forex_agent/
  apps/            Composition root: FastAPI app, routers, settings loading.
                   Only layer allowed to read environment variables directly.
  application/     Use cases + ports (interfaces) that infrastructure
                   implements. Depends only on domain.
  domain/          Entities, value objects, domain services. No dependency on
                   FastAPI, SQLAlchemy, OANDA SDK/API objects, HTTP clients,
                   or environment variables.
  infrastructure/  SQLAlchemy repositories (infrastructure/db), OANDA adapter
                   (infrastructure/broker_oanda). Implements application
                   ports. Provider-specific objects must not escape this
                   layer.
```

Enforcement is currently by review discipline (see CLAUDE.md's "Architecture
boundaries" and the definition-of-done checklist item "Architecture
boundaries preserved"). If import-linter or a similar dependency-direction
checker is added later, record that decision here and in `docs/adr/`.

## Execution pipeline

Every executable order must originate from:

```
trade hypothesis -> risk decision -> approved execution intent -> order
```

No code path may bypass risk approval, execution intent creation, kill
switches, or account reconciliation. See CLAUDE.md "Safety rules".

## Point-in-time fundamental data (FX-41)

`domain/macro_series_definition.py` and `domain/macro_observation_vintage.py`
give the codebase a provider-independent way to represent a macro/
fundamental fact (a CPI print, a policy rate, ...) without collapsing when
the market could actually know it into when it happened. This is a
foundation-only story: no provider is integrated, no ingestion pipeline
exists, and no strategy or scoring logic consumes this data yet — see
`docs/DECISIONS.md` for the full rationale.

Five invariants this data model exists to protect:

1. **Observation time is not publication time.** A `MacroObservationVintage`
   carries `observation_period` (which reference period a value describes)
   and `released_at` (when that value first became publicly knowable) as
   two independent fields. A February CPI print released March 12 has
   `observation_period` in February and `released_at` in March — nothing in
   this codebase is allowed to conflate the two.
2. **Historical fundamental research must be point-in-time correct.** Both
   `MacroObservationRepository` query methods
   (`latest_available_as_of`/`observation_as_known_at`) filter on
   `released_at <= as_of` — a query about a past instant can only see
   vintages that instant could actually have seen. This mirrors, for
   fundamental data, the same no-look-ahead discipline FX-11H established
   for candle data.
3. **Revisions/vintages are preserved, never overwritten.** A revision is
   a new `MacroObservationVintage` row with a later `released_at` and a
   higher `revision_sequence` for the same `(series_key,
   observation_period)`. `SqlAlchemyMacroObservationRepository` has no
   UPDATE anywhere in it — every write is `INSERT ... ON CONFLICT DO
   NOTHING`, so a historical vintage can never be mutated once stored.
   FX-41H hardened this further: `add_vintage` is idempotent for an
   exact retry, but raises `MacroVintageConflictError` if a vintage
   with the same identity already exists with a *different* payload —
   a silent no-op would otherwise hide a caller bug or a non-immutable
   source behind what looks like a successful write. Query ordering
   (`latest_available_as_of`/`observation_as_known_at`) also breaks
   ties on identical `released_at` values by `revision_sequence`
   descending, so retrieval never depends on scan order.
4. **Unsafe latest-only historical data must not be treated as
   research-safe.** `PointInTimeSafety` (`POINT_IN_TIME_SAFE`,
   `LATEST_ONLY`, `UNKNOWN`) classifies whether a source actually
   preserves revision history. FX-41 originally put this classification
   on `MacroSeriesDefinition` itself; **FX-42H removed it from there** —
   a canonical economic concept is provider-independent by construction
   and has no source of its own to classify. It now lives solely on
   `ProviderSeriesMapping.point_in_time_safety` (FX-42, see below), and
   `require_research_usable_mapping` (FX-42H) is the fail-closed guard:
   a mapping is research-usable only when it is BOTH `verified` (its
   identifier has been confirmed against the live provider) AND
   classified `POINT_IN_TIME_SAFE` — either condition alone is
   insufficient, so a future research/strategy consumer cannot silently
   trust an unverified, latest-only, or merely-plausible-looking source.
5. **This story contains no trading hypothesis.** No policy-rate ingestion,
   no FRED/central-bank API client, no economic calendar, no carry or
   rate-differential strategy, no fundamental score, no BUY/SELL decision
   logic. Just the data model and its point-in-time safety invariant.

## Canonical policy-rate registry (FX-42; hardened FX-42H, FX-42H.1)

`domain/policy_rate_registry.py` defines, for USD/EUR/GBP/JPY/CAD, exactly
one canonical policy-rate concept per currency — still no ingestion, no
strategy, purely semantics and provider mappings, built on FX-41's
foundation. It introduces the split FX-41 deferred: canonical economic
identity (`MacroSeriesDefinition`, provider-independent) versus
provider/source mapping (`ProviderSeriesMapping`, which provider and
identifier(s) actually supply the data, and — since FX-42H — that
mapping's own, sole-source-of-truth point-in-time safety; see invariant 4
above and `docs/DECISIONS.md`'s FX-42/FX-42H entries for the full
reasoning).

Central banks do not express monetary policy identically, and a single
institution's own practice can change over time — sometimes in a way that
still describes one continuous concept (the ECB's Main Refinancing
Operations rate, or the Federal Reserve's shift from a single target rate
to a target range in December 2008), and sometimes in a way that changes
the INSTRUMENT TYPE itself: the Bank of Japan's quantitative-easing eras
targeted a quantity (the balance of current accounts, or the monetary
base), not a scalar interest rate, so no canonical policy-RATE definition
covers those periods at all. `PolicyRateDefinition` represents one
effective-dated interpretation of a currency's canonical series —
`valid_from`/`valid_to` bound exactly when it applies (a half-open
window), and `transformation` (`RateTransformation`, explicit and
versioned) says precisely how raw provider value(s) become one canonical
`Decimal` during that window. Multiple `PolicyRateDefinition`s for one
currency always share one canonical `MacroSeriesDefinition` — not merely
the same `key` string, but fully identical semantics (economy, currency,
category, unit, frequency), enforced by `validate_registry` at import
time — so a future query against `MacroObservationRepository` never needs
to know which era's instrument mechanics produced a given historical
value. `validate_registry` rejects overlapping validity windows.

Gaps between consecutive definitions must now be explicitly DECLARED
(FX-42H.1): FX-42H's blanket tolerance for any gap could not distinguish
an intentional one (the Bank of Japan's quantity-target eras) from an
accidental one (a boundary typo, a forgotten definition). A
`DeclaredPolicyRateGap` (`domain/declared_policy_rate_gap.py`) names a
currency, a half-open `[start, end)` window, and a non-empty `reason`;
`validate_registry` requires every gap between two consecutive
definitions for a currency to be covered by EXACTLY one declared gap with
matching boundaries, rejects a declared gap that overlaps an actual
definition, and rejects declared gaps that overlap each other. An
undeclared gap is now a validation error, not a silently accepted state.
`definition_as_of` still returns `None` for an instant inside a declared
gap, exactly representing "no comparable canonical scalar existed for
this period" rather than fabricating a value — see JPY's two declared
gaps (2001-2006 Quantitative Easing, 2013-2016 Quantitative and
Qualitative Easing) in `policy_rate_registry.py`.

FX-42/FX-42H/FX-42H.1 were intentionally narrow: semantics and provider
mappings only, no rate history downloaded. FX-43 (below) is the ingestion
story that changed that.

## Policy-rate history backfill (FX-43)

`application/use_cases/backfill_policy_rate_history.py`
(`BackfillPolicyRateHistory`) is the first use case in this codebase that
ingests real external fundamental data. It composes already-established
machinery rather than inventing new architecture:

```
policy_rate_registry.definitions_for_currency(currency)
        v
PolicyRateHistoryProvider.fetch_daily_series(...)   (one per raw series)
        v
domain.policy_rate_change_extraction.extract_change_points(...)
        v
MacroObservationVintage(...) per genuine change point
        v
MacroObservationRepository.add_vintage(...)          (FX-41H idempotent)
```

`PolicyRateHistoryProvider` (`application/ports/
policy_rate_history_provider.py`) is a minimal port: one provider-specific
series ID and a date range in, raw `(date, Decimal)` pairs out — no
canonicalization, no transformation, no `MacroObservationVintage`
construction. Four concrete implementations
(`infrastructure/policy_rate_providers/`) talk to FRED, the ECB Data
Portal, the Bank of England database, and the Bank of Canada Valet API —
all four confirmed live, no API key needed for any of them.

`domain/policy_rate_change_extraction.py` (`extract_change_points`) is
this story's anti-interpolation guarantee, kept as a pure, provider-
independent function: a provider's raw daily series typically repeats the
same value every day it stayed in effect (a step function published
daily, not evidence of daily decision-making). This function reduces that
down to genuine policy CHANGES only — one `MacroObservationVintage` per
date the canonical value actually moved, never a fabricated one for a
date it wasn't given (a date present in one input series but not another,
needed only for `TARGET_RANGE_MIDPOINT`, is skipped and reported, never
paired with a guessed value).

Idempotent by construction: every vintage goes through
`MacroObservationRepository.add_vintage`, whose FX-41H conflict handling
already makes an exact-duplicate re-run a no-op — this story adds no new
idempotency mechanism, it relies on the existing one. Confirmed live: the
real backfill script was run twice against the real APIs and a real
Postgres, with identical counts and zero conflicts both times.

`released_at` for every ingested vintage is set to the date a provider's
raw series shows a genuine value change — an EFFECTIVE-DATE proxy, not a
verified announcement/publication timestamp. This is a known, explicitly
documented limitation, not an oversight: no `ProviderSeriesMapping` is
promoted to `PointInTimeSafety.POINT_IN_TIME_SAFE` as a result of this
story, and `require_research_usable_mapping` continues to fail closed for
every mapping in the registry — see `docs/DECISIONS.md`'s FX-43 entry for
the full reasoning and what a future story establishing genuine
announcement timestamps would need to do.

`scripts/backfill_policy_rate_history.py` wires this together against a
live Postgres and the four real providers, writing
`reports/policy_rate_backfill_report.json` — the explicit, per-currency
data-quality report this story requires (coverage actually achieved, not
merely requested; skipped dates; conflicts; unconfigured/failed eras;
known gaps).

## Policy-rate backfill hardening (FX-43H)

Four gaps found running the FX-43 pipeline for real (see
`docs/DECISIONS.md`'s FX-43H entry) were closed before any rate-
differential research consumes this data:

1. **Half-open era boundaries, enforced against the provider fetch
   itself.** Registry validity is `[valid_from, valid_to)`, but provider
   APIs are queried by inclusive calendar-date range. `BackfillPolicyRate
   History._fetch_end` now clamps an era's requested end to `valid_to -
   1 day` whenever the window would otherwise reach the next era's start
   — never relying on a specific provider happening to stop publishing
   the day before (confirmed as a real risk: FRED's `DFEDTAR` does, but
   that is a fact about FRED, not a guarantee to lean on).
2. **Raw provider coverage kept separate from change-point span.**
   `EraBackfillReport` now carries `earliest_raw_observation`/`latest_raw
   _observation` (the true span of data received) alongside `earliest_
   change_point`/`latest_change_point` (the narrower span of genuine
   rate changes) — `CurrencyBackfillReport.coverage_start`/`coverage_end`
   aggregate from the RAW fields. A stable rate that stops changing but
   keeps being published daily now correctly reports coverage extending
   to the present, not to its last change.
3. **`add_vintage` reports INSERTED vs ALREADY_PRESENT.**
   `VintageWriteOutcome` (`application/ports/
   macro_observation_repository.py`) replaces `add_vintage`'s `None`
   return; `MacroVintageConflictError` is unchanged for genuine
   conflicts. The backfill use case reports `vintages_inserted`/
   `vintages_already_present` accurately instead of one undifferentiated
   count.
4. **Duplicate raw observations never resolved by "last value wins."**
   `extract_change_points` now raises `ConflictingRawObservationError`
   when one raw series reports two DIFFERENT values for the same date
   (an identical repeat still collapses harmlessly); the use case
   catches this and reports it as an explicit `data_integrity_error`.

A fifth change addresses the release/effective-timestamp distinction
directly: every vintage `BackfillPolicyRateHistory` writes is now
explicitly marked `released_at_is_verified=False`
(`MacroObservationVintage`, FX-43H) — making FX-43's effective-date-proxy
limitation part of the stored data, not just prose documentation.
`MacroObservationRepository` gained `replace_provisional_release_timing`,
a narrowly-scoped exception to the "never UPDATE" rule: it corrects an
existing PROVISIONAL row's `released_at`/`effective_at` in place
(refusing if the row is already verified), without ever touching `value`
or `revision_sequence` — a release-timing correction is never represented
as an economic revision. No caller of it exists yet; FX-43H's job was to
make replacement possible and safe, not to perform it (no verified
announcement timestamp exists yet to replace anything with).

## Provisional timestamp fail-closed hardening (FX-43H.1)

Two remaining gaps in FX-43H's own `released_at_is_verified`/
`replace_provisional_release_timing` mechanisms (see
`docs/DECISIONS.md`'s FX-43H.1 entry) were closed:

1. **`released_at_is_verified` now defaults to `False`**, at both the
   domain (`MacroObservationVintage`) and SQLAlchemy-model layers. A
   caller that has not actually confirmed release timing gets a
   provisional vintage by default; claiming verification requires
   passing `released_at_is_verified=True` explicitly. Migration
   `80c0ae20257b` carries this into the database two ways: it changes
   the column's `server_default` for future rows, AND it
   unconditionally reclassifies every row that already exists when it
   runs to `False` — a schema-default change alone would not have
   fixed rows already written under the old default, and this
   codebase does not rely on an operator manually clearing or
   reloading data to reach a correct state.
2. **`replace_provisional_release_timing` is now a single atomic
   conditional `UPDATE ... WHERE ... AND released_at_is_verified =
   false ... RETURNING id`**, not a SELECT-then-UPDATE. The
   provisional-row check and the write are the same statement, so two
   concurrent callers racing the same identity cannot both succeed —
   Postgres's row lock serializes them, and the second to commit
   re-evaluates its own `WHERE` clause against the now-verified row
   and correctly updates nothing. A `SELECT` after a non-matching
   UPDATE exists only to distinguish "no such vintage" from "already
   verified" for the error message; it never decides whether a write
   happens.

## Point-in-time policy-rate release verification (FX-44)

The first real use of FX-43H/FX-43H.1's replacement mechanism: cited,
researched release-timing rules applied to USD/EUR/GBP/CAD's real
change points (see `docs/DECISIONS.md`'s FX-44 entry for the full
per-currency research). JPY stays out of scope.

`domain.release_timing_rule.ReleaseTimingRule` is a pure, cited data
type -- institution, local time-of-day, IANA timezone, validity
window, citation -- with a `ReleaseTimingConfidence`:

- `EXACT`: a specific, documented institutional convention. Produces a
  genuinely defensible timestamp; safe to claim `released_at_is_
  verified=True`.
- `CONSERVATIVE_SAFE_BOUND`: the exact minute is not confidently
  citable, but a same-day/business-hours convention is confirmed, so a
  deliberately LATE bound (e.g. end of the announcement day, local
  time) is used instead -- guaranteed no earlier than the true
  release, and therefore safe for point-in-time research, but never
  claimed as the exact moment.

`ReleaseTimingRule.resolve()` uses `zoneinfo` (the stdlib's own
historical IANA timezone database) to convert a local date into an
exact UTC instant with the correct historical DST offset for that
specific date -- this module hand-codes zero DST transition dates
itself, and a rule expressed once therefore converts correctly across
every year it covers.

`domain.policy_rate_release_timing_registry.resolve_release_timing`
is the per-currency dispatch: it applies the researched rules ONLY to
change points confirmed to be regular, scheduled decisions, and
returns an explicit `UnresolvedTiming` (with a reason) for every known
irregular/inter-meeting/emergency date or under-researched era, rather
than ever inferring an exact timestamp merely from the daily rate
series. EUR is the one currency with a genuine, documented
announcement-before-effective-date split: its stored proxy date is the
EFFECTIVE date (confirmed computationally -- every relevant stored
date is a Wednesday, matching the ECB's own published "first
operation following the decision" methodology), so `released_at` is
set to the earlier Thursday decision date/time while `effective_at`
keeps the later, original stored date.

`MacroObservationVintage.released_at_is_conservative_bound: bool =
False` (new field, migration `aee1fa641be6`) is the conservative
counterpart to `released_at_is_verified` -- FX-44 is explicit that
`released_at_is_verified=True` must never be overloaded to mean "we
guessed a safely late time." `replace_provisional_release_timing`'s
atomic UPDATE predicate was extended to require BOTH outcome flags
`False` (a still-fully-provisional row) before either can be written,
and it now takes a `confidence: ReleaseTimingConfidence` parameter
deciding which flag gets set.

`application.use_cases.verify_policy_rate_release_timing.
VerifyPolicyRateReleaseTiming` is the first real caller of `replace_
provisional_release_timing`: for each of a currency's stored change
points, it resolves via the registry and either replaces a still-
provisional row, leaves an unresolved one untouched, or -- for a row
ALREADY classified -- compares against what the registry resolves to
NOW and reports a clean no-op (identical timing) or an explicit
`CONFLICTING` outcome (a mismatch) without ever overwriting. Idempotent
by construction: re-running finds nothing left to write for anything
it already classified.

`domain.research_readiness.require_research_ready_interval` is FX-44's
critical invariant as code, and the mandatory pre-flight check a
future FX-45 must call: it raises if ANY vintage in the caller's
selected interval is neither `released_at_is_verified` nor
`released_at_is_conservative_bound` -- a single provisional observation
fails the whole interval, no partial pass.

No `ProviderSeriesMapping.point_in_time_safety`/`verified` field is
promoted for any currency -- every currency still has unresolved
change points across its full stored history, and promotion requires
the entire research interval to qualify, not merely some observations
within it. `research_results/fx44/policy_rate_release_verification.
json` (written by `scripts/verify_policy_rate_release_timing.py`)
represents interval-specific safety explicitly instead, per currency.

## Release-timing semantic hardening (FX-44H)

FX-44 shipped one real bug (USD's modern announcement/effective
semantics) and four related structural gaps; this story fixes all
five (see `docs/DECISIONS.md`'s FX-44H entry for the full research and
live verification).

**USD's EXACT tier is now an explicit, individually-cited `dict[date,
date]`** (`USD_EFFECTIVE_TO_DECISION_DATE`), not a formula. FX-44's
original resolver treated FRED's stored change-point date as both the
announcement date and the effective date; it is actually only the
latter -- the FOMC's own "Implementation Note" states a genuinely
later effective date (one day later, in every one of the 30 currently
EXACT-classified USD change points this story individually verified
against the Fed's own published meeting calendars). A blind `-1 day`
transformation would have been wrong for two of those thirty
(2015-12-16 "liftoff" and 2016-12-14 both have a same-day gap) --
exactly the kind of case an unverified formula would miss, which is
why the EXACT tier has no formula at all: a USD date not present as an
explicit mapping key is unresolved, full stop, including a future date
a later backfill run ingests.

**Remediating rows FX-44 already wrote required a genuinely separate
mechanism, `MacroObservationRepository.correct_verified_release_
timing`** -- not a relaxed `replace_provisional_release_timing`.
`replace_provisional_release_timing`'s entire safety contract is
refusing to touch an already-classified row; correction targets
exactly that row, on purpose, when the classifier itself was later
found wrong. Its atomic UPDATE therefore has the OPPOSITE precondition
(`released_at_is_verified = true`, not `false`) plus an exact match on
the caller's `expected_current_released_at`/`expected_current_
effective_at` -- an optimistic-concurrency guard, proven by a
dedicated `asyncio.gather` regression, that makes a second correction
attempt (accidental or concurrent) fail closed rather than silently
reapplying or racing. `application.use_cases.remediate_release_
timing.RemediateReleaseTiming` drives this deliberately, as its own
separate operation (`scripts/remediate_usd_release_timing.py`) --
never automatically as part of routine verification -- comparing every
currently-EXACT vintage against what the registry resolves NOW and
correcting only a genuine mismatch; idempotent by construction.

**Research readiness now accounts for carry-in state.**
`require_research_ready_interval` originally judged only vintages
whose `observation_period` fell inside the selected interval --
insufficient, because a point-in-time query anywhere in an interval
with zero in-interval changes still returns whatever vintage was
carried in from before it. New `domain.research_readiness.select_
research_candidates` derives BOTH the carry-in state (the latest
`observation_period` at or before `interval_start`) and the
in-interval observations from a series' COMPLETE stored history, so a
caller cannot get this wrong by hand-selecting candidates --
`require_research_ready_interval` now takes that complete history
directly. An entirely empty derived candidate set (no carry-in, no
in-interval observations either) fails closed too (`no_baseline` on
`ResearchIntervalNotReadyError`) -- "no evidence" is not "nothing
wrong found".

**Exact/conservative mutual exclusivity is now structurally
enforced** at both the domain layer (`MacroObservationVintage.
__post_init__` rejects both flags `True` at once) and the persistence
layer (migration `f350d505412b`'s `ck_macro_observation_vintages_
exclusive_timing_confidence` CHECK constraint) -- previously asserted
only by docstring convention.

**ECB citations now point to the ECB's own official 27 June 2022
press release** (not a tweet or a news aggregator), and `_resolve_eur`
structurally requires `stored_date.weekday() == Wednesday` before ever
applying its six-day announcement/effective transformation --
previously this safety depended entirely on a hand-curated exclusion
list catching every anomaly in advance. `EUR_EXPLICIT_DECISION_DATE_
OVERRIDES` (empty today) is the only sanctioned escape hatch for a
genuinely researched non-Wednesday exception.

## USD effective-date correction (FX-44H.1)

FX-44H correctly separated the FOMC decision date from the provider-
stored change-point date, but silently assumed the stored date always
equals the genuine operational EFFECTIVE date too -- an assumption
that was itself wrong for the two rows FX-44H had already flagged as
needing special handling (2015-12-16, 2016-12-14): the Fed's own
Implementation Notes place both rows' true effective date one day
AFTER the decision date, the same gap every other mapped meeting has.

`USD_EFFECTIVE_TO_DECISION_DATE: dict[date, date]` is replaced by
`USD_POLICY_TIMINGS: dict[date, UsdPolicyTiming]` -- `stored_date`,
`decision_date`, and `effective_date` as three genuinely independent
fields on a new domain type, never assumed equal to one another by a
formula. This is not a two-column mapping with a third column bolted
on: the type exists specifically so a future discrepancy between the
provider's date and the true effective date, for any USD meeting,
cannot silently reintroduce this class of bug. `_resolve_usd` reads
`effective_at` from `timing.effective_date` (via `_date_only_as_utc_
midnight`, a normalization helper whose docstring is explicit that
`00:00 UTC` represents a date-only fact, never a claimed intraday
instant -- `MacroObservationVintage.effective_at`'s own docstring
carries the same caveat now) -- never from `observation_period`
directly.

Remediation went through FX-44H's existing `RemediateReleaseTiming`/
`correct_verified_release_timing` mechanism completely unmodified --
exactly the value of having built it as a genuinely reusable
mechanism rather than a one-off script.

## Pair-relative policy-rate differential (FX-45)

A deterministic, fully-auditable monetary-policy feature -- `domain.
policy_rate_differential = base_currency_rate - quote_currency_rate`,
`Decimal` only, never called "carry" anywhere in this codebase (it is
not a tradeable financing return, not an interest-rate strategy, not a
rate-arbitrage signal -- see that module's own docstring). Built
entirely on top of FX-44H/FX-44H.1's release-timing model rather than
introducing a new one.

**Two rate-state notions, kept structurally separate.** New `domain.
policy_rate_state` answers "which decision governs a currency's policy
rate at instant T" two distinct ways that must never substitute for
one another: `announced_state_as_of` (market-known, gated on
`released_at <= T` -- a future-effective-but-already-announced rate IS
the announced rate, deliberately) and `effective_state_as_of`
(operationally in force, gated on a POPULATED `effective_at <= T`,
strictly excluding any vintage whose `effective_at` is `None` rather
than falling back to `released_at` or `observation_period`). These are
two distinctly-named functions, not one function with a mode flag, so
a caller cannot accidentally request the wrong semantics and silently
get the other one. Neither function consults research readiness
itself -- they answer "what does the stored history say," not "is it
safe to trust."

**Raise vs. return, deliberately not conflated.** `application.
use_cases.compute_policy_rate_differential.ComputePolicyRateDifferential`
is the single use case orchestrating this against real repository
history. Two distinct kinds of "no answer" exist: unsafe or
insufficient DATA -- `domain.research_readiness.
ResearchIntervalNotReadyError` is RAISED, the existing FX-44H
mechanism completely unmodified; a structurally unsupported REQUEST
(a currency with no canonical policy rate at all, e.g. XAU; or
EFFECTIVE semantics for a currency/vintage that has never had a
verified effective date, e.g. GBP or CAD today) -- `domain.
policy_rate_differential.DifferentialUnavailable` is RETURNED. JPY
(registered in `domain.policy_rate_registry` but zero ingested rows,
per FX-43/FX-43H) naturally falls into the raise path via the
readiness gate's own `no_baseline` case, needing no special-case
currency list.

**Axis-safety margin.** `require_research_ready_interval`/`select_
research_candidates` (FX-44H) window on `observation_period`, while
this story's state selection windows on `released_at`/`effective_at`
-- different axes that are usually close but never assumed identical.
A fixed `_AXIS_SAFETY_MARGIN` (14 days -- more than double the largest
offset this registry has ever found, EUR's historical six-day
announcement/effective gap) pads every readiness-window bound, so a
state-selection result is always provably covered by the readiness
check that ran for it.

**Change companions.** `PolicyRateDifferentialFeature` carries three
independently-computed changes alongside the current snapshot --
since the previous policy observation, ~3 months, and ~6 months --
each with its own purely mathematically-defined `DifferentialDirection`
(`WIDENING`/`NARROWING`/exact-zero `UNCHANGED`; no fuzzy band, no
tuned threshold). "Change since previous policy observation" for a
PAIR uses a "last-mover reversion": only the leg whose current state
began more recently is reverted to its own previous state (both legs,
on an exact tie), since the other leg's rate did not change at that
instant. Any change FX-45 cannot defensibly compute is `None` with a
`None` direction -- never a guessed value or a default `UNCHANGED`.

**No scoring, no thresholds, no trading labels anywhere in this
feature** -- every result type carries full per-leg provenance
(currency, rate, source series/observation, `released_at`,
`effective_at`, verification tier) instead, by design.

## Policy-rate differential point-in-time & coverage hardening (FX-45H)

Three real point-in-time gaps in FX-45's own state-selection and
readiness logic, found and fixed without touching any accepted FX-45
architecture or terminology.

**1. EFFECTIVE state is now point-in-time safe.** `effective_state_
as_of` originally selected the latest `effective_at <= T` WITHOUT also
requiring `released_at <= T` -- wrong: a revision can carry an OLD
`effective_at` but a `released_at` that is itself still in the future
(a retroactively-disclosed or corrected effective date). New `domain.
policy_rate_state.known_as_of(vintages, as_of)` is the single shared
`released_at <= as_of` filter every function in the module now applies
first, before doing anything else with a vintage -- a fact not yet
released by `T` cannot affect any point-in-time query evaluated at
`T`, no matter how favorably its other dates line up.

**2. Fail closed on an intervening decision with unknown effective
timing.** Even PIT-safe, a second gap remained: an OLD decision with a
populated `effective_at` could still be reported as "the" effective
state even when a NEWER decision has already been released with its
OWN `effective_at` not yet established -- silently assuming the newer
decision has not yet taken effect, which cannot be verified either
way. `effective_state_as_of`/`previous_effective_state` both now
detect this (ordered by `observation_period`, the only axis available
for a vintage with no `effective_at`) and return `None` instead.
`previous_effective_state` gained an explicit `as_of` parameter to
apply the identical PIT filter for the "previous" search (its own
axis mismatch -- an early `effective_at` can still carry a late
`released_at` -- means this is NOT, unlike `previous_announced_
state`, automatically implied by `current` already being PIT-safe).

**3. A not-yet-released observation can no longer block a historical
query.** The `_AXIS_SAFETY_MARGIN` readiness window previously padded
`end` forward by 14 days from `as_of` UNCONDITIONALLY -- sweeping in
any vintage whose `observation_period` fell in that padding zone,
including ones not yet released as of `as_of`, and blocking the whole
query if such a vintage happened to be provisional (real example: a
genuine USD row dated 1998-10-15, released_at == observation_period
== 1998-10-15 itself, i.e. not yet released as of 1998-10-08, wrongly
blocked a GBP/USD query at that instant). `ComputePolicyRateDifferential`
now narrows each currency's full history to `known_as_of(history,
as_of)` BEFORE either state selection or the readiness check ever
runs, and `_readiness_window`'s baseline `end` no longer pads
unconditionally -- it only extends past `as_of` as far as `current`'s
own `observation_period` actually requires. Confirmed safe for FX-44H's
carry-in mechanism by direct SQL against the real dataset first: the
largest `released_at`-vs-`observation_period` gap ever found, in
either direction, is under six days (EUR) -- far inside both the
multi-month lookbacks and the margin itself, so a genuine carry-in
candidate is never excluded by this filter in practice, only a vintage
that truly was not yet known.

**4. The margin is documentation, not proof.** `_AXIS_SAFETY_MARGIN`'s
own comment and this module's docstring no longer describe 14 days as
provably sufficient because the largest observed gap is six -- that
reasoning does not generalize to a future regime. Correctness now
rests on `known_as_of`'s exact filter; the margin is explicitly
documented as defensive padding layered on top of it, for the
narrower, still-real need of covering `current`/`previous`'s own
`observation_period` skew.

GBP/CAD's EFFECTIVE-semantics unavailability is described as
"currently unavailable with present effective-date coverage" from this
story onward (not "permanently unavailable" -- FX-45's own wording
overclaimed permanence for what is, in fact, a present data-coverage
fact that a future backfill could change).

## Policy-rate readiness & revision semantics hardening (FX-45H.1)

A narrow hardening pass on FX-45H -- every fix corrects this
codebase's own logic, none required new external research.

**State selection and research readiness no longer share one
destructively filtered view.** A provisional vintage's `released_at`
may be an uncorroborated proxy (FX-43H), never a verified knowability
instant -- FX-45H's `known_as_of` pre-filtered history by it before
handing that SAME filtered view to BOTH state selection AND `require_
research_ready_interval`, letting a genuinely relevant provisional row
silently vanish from readiness consideration instead of correctly
failing the interval closed. `known_as_of` is renamed `_released_at_
on_or_before` and made private -- used only internally by state
selection, which may still use this mechanical filter (it must pick
SOME candidate). `ComputePolicyRateDifferential` no longer pre-filters
at all: state selection and the readiness check both receive the SAME
complete, unfiltered series history directly, matching FX-44H's
original contract for `require_research_ready_interval`. Verified
directly, not assumed, that the real 1998-10-15 worked example (FX-45H's
own) still correctly stays out of the readiness window -- via its
`observation_period` falling outside the computed window bound, not
via trusting its own `released_at`.

**ANNOUNCED state selects by observation identity, not raw `released_
at`.** A revision published later for an OLDER observation_period (a
correction to a stale figure) could have a `released_at` exceeding a
genuinely newer, unrevised observation's own -- wrongly resurrecting
the older observation as "current". New two-step selection: among
vintages knowable at `T`, find the latest `observation_period` with
any representative at all, then pick that observation's own latest
admissible revision. `previous_announced_state` needed the identical
treatment and gained an explicit `as_of` parameter as a result.

**A same-observation higher revision can ALSO leave EFFECTIVE
unresolved**, not only a later, different observation_period --
`revision_sequence` is reserved for genuine value corrections to the
SAME decision, so an unresolved higher-revision sibling supersedes an
older, lower-revision sibling's own effective timing just as a
genuinely later decision would. Both `effective_state_as_of` and
`previous_effective_state` now check for this.

The FX-45H `GBP/USD ANNOUNCED 78 -> 80` improvement was explicitly
verified, not assumed, to remain valid after these fixes -- a full
diff of the regenerated coverage diagnostic shows zero verdict flips;
the two specific instants FX-45H unblocked were always excluded via
the readiness window's own bound, never via trusting either offending
row's provisional proxy. A real, previously-uncaught instance of the
actual bug DID surface on regeneration: several already-blocked
entries (USD `2020-03-04`, GBP `1997-06-02`) now correctly list an
additional offending observation each that FX-45H's design had
silently pruned from consideration -- the verdict for each was already
blocked for an unrelated reason, so no usable/blocked count changed,
but the reported reason is now complete rather than silently partial.

## Historical policy-rate differential research (FX-46)

The first real research EXPERIMENT run against the FX-45/FX-45H/
FX-45H.1 feature -- deliberately a thin layer ON TOP of that feature,
never a reimplementation of it.

**A pure module plus exactly one async seam.**
`src/forex_agent/research/policy_rate_differential_research.py` holds
every classification, sampling, event-detection, return-computation,
and descriptive-statistics function as a plain synchronous function
over domain values -- no database, no HTTP, fully unit-testable
without infrastructure, matching this project's own domain-layer
boundary rules even though this module lives under `research/` rather
than `domain/` (it is FX-46-specific, not a general domain concept,
so it is kept separate rather than widening `domain/`'s own surface).
Exactly one function, `evaluate_feature`, is async and touches
`ComputePolicyRateDifferential` -- the single place anywhere in FX-46
that reads policy-rate state, normalizing that use case's raise
(`ResearchIntervalNotReadyError`) vs. return (`DifferentialUnavailable`)
split (FX-45H) into one `Disposition` enum the rest of the pipeline
can classify and count uniformly, without ever falling back between
`ANNOUNCED`/`EFFECTIVE` or imputing a value around a non-`USABLE`
result.

**Orchestration owns aggregation; the pure module does not.**
`scripts/run_fx46_policy_rate_differential_research.py` holds the real
DB/candle-repository wiring, the per-cell statistics, the primary-
contrast bootstrap, the era breakdown, and the JSON/CSV/markdown
writers -- mirroring FX-39's own script (`run_fx39_significance_
testing.py`), which established the precedent that script-specific
shaping/reporting logic belongs in the script, not a second pure
module competing with the first. This keeps the pure module's public
surface small and independently testable, while the script stays the
one place that can change (a new output format, a new grouping) without
touching tested domain-shaped logic.

**A read-through cache wraps the repository port, never bypasses it.**
`_CachingMacroObservationRepository` (script-local) implements the
full `MacroObservationRepository` Protocol, memoizing only `list_all_
for_series` -- every other method (including all three write methods,
never actually called by this read-only script) delegates unchanged.
This is safe specifically because the script never writes: a series'
stored history cannot change out from under the cache mid-run. It
exists purely because `ComputePolicyRateDifferential`'s own FX-45H.1
correctness contract requires being handed each currency's COMPLETE
history on every call -- with ~41,000 feature evaluations across this
experiment's full scope but only 4 distinct currencies in play, caching
that repeated, unchanging read is a pure performance optimization at
the orchestration layer; it does not alter what the use case sees or
weaken any point-in-time guarantee.

**One daily sweep serves both experiments.** The LEVEL experiment's
weekly samples are, by construction, a subset of the CHANGE
experiment's "every canonical D-bar open" evaluation set. The
orchestration script evaluates the feature once per D-bar per (pair,
semantics) and derives both experiments' samples from that one set of
results, rather than evaluating the feature twice. Safe because
`evaluate_feature` is a pure function of `(instrument, as_of,
semantics)` -- reusing a result changes nothing about what would have
been computed evaluating it again.

**No native daily candles exist; the existing aggregation use case
materializes them.** `scripts/aggregate_d_candles.py` calls the
existing `AggregateCandles` use case (FX-7) to build `D` bars from
native `H4` (already 17:00 America/New_York-aligned, FX-24/FX-25H) --
not a new data-access path. `aggregate_candles` drops any bucket whose
source candles don't exactly tile it, so a `D` bar is never fabricated
from a partial, gappy, or DST-shortened `H4` set.

**The bootstrap gains a two-group contrast primitive, in place.**
`domain/block_bootstrap.py` (FX-39) gained `calendar_year_cluster_
bootstrap_differences` rather than a new, parallel bootstrap module --
the natural extension of the file's own existing `segment_block_
bootstrap_means` shape (resample whole clusters with replacement, pool,
take the pooled mean) to a difference-of-means contrast between two
groups sharing one clustering variable. `NUM_RESAMPLES = 10_000`
(FX-39's own convention) is reused unchanged rather than introducing a
second, competing default.

## Current state

Scaffolding only — see [CURRENT_STATE.md](CURRENT_STATE.md) for what actually
exists today versus what this document describes as the target shape.
