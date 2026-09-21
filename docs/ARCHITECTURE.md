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
   `LATEST_ONLY`, `UNKNOWN`) classifies whether a series' source actually
   preserves revision history. `MacroSeriesDefinition` defaults to
   `UNKNOWN`, and `require_point_in_time_safe` fails closed — it raises
   for anything that isn't explicitly `POINT_IN_TIME_SAFE` — so a future
   research/strategy consumer cannot silently trust an unverified or
   latest-only source.
5. **This story contains no trading hypothesis.** No policy-rate ingestion,
   no FRED/central-bank API client, no economic calendar, no carry or
   rate-differential strategy, no fundamental score, no BUY/SELL decision
   logic. Just the data model and its point-in-time safety invariant.

## Canonical policy-rate registry (FX-42)

`domain/policy_rate_registry.py` defines, for USD/EUR/GBP/JPY/CAD, exactly
one canonical policy-rate concept per currency — still no ingestion, no
strategy, purely semantics and provider mappings, built on FX-41's
foundation. It introduces the split FX-41 deferred: canonical economic
identity (`MacroSeriesDefinition`, provider-independent) versus
provider/source mapping (`ProviderSeriesMapping`, which provider and
identifier(s) actually supply the data, and that mapping's own
point-in-time safety — see `docs/DECISIONS.md`'s FX-42 entry for the full
reasoning).

Central banks do not express monetary policy identically, and a single
institution's own practice can change over time (the Federal Reserve's
December 2008 shift from a single target rate to a target range is this
registry's example). `PolicyRateDefinition` represents one effective-dated
interpretation of a currency's canonical series — `valid_from`/`valid_to`
bound exactly when it applies, and `transformation`
(`RateTransformation`, explicit and versioned) says precisely how raw
provider value(s) become one canonical `Decimal` during that window.
Multiple `PolicyRateDefinition`s for one currency always share the same
`MacroSeriesDefinition.key`, so a future query against
`MacroObservationRepository` never needs to know which era's instrument
mechanics produced a given historical value — `policy_rate_registry`'s own
`validate_registry` enforces this (and non-overlapping, gap-free validity
windows) at import time, failing fast on a malformed registry.

This story is intentionally narrow: it defines semantics and provider
mappings only. No rate history is downloaded, no pair differential is
computed, no carry strategy exists, and every `ProviderSeriesMapping` in
the registry is `verified=False` — see the module's own docstring and
`docs/DECISIONS.md` for what FX-43 (ingestion) still needs to confirm
before any of this data reaches a `MacroObservationRepository`.

## Current state

Scaffolding only — see [CURRENT_STATE.md](CURRENT_STATE.md) for what actually
exists today versus what this document describes as the target shape.
