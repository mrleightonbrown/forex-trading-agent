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

## Current state

Scaffolding only — see [CURRENT_STATE.md](CURRENT_STATE.md) for what actually
exists today versus what this document describes as the target shape.
