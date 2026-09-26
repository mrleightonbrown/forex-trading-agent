# Current State

_Last updated: 2026-09-26 (FX-51H.1)_

## What exists

- Repository scaffolding: `apps/application/domain/infrastructure` package
  layout under `src/forex_agent/`, `tests/{unit,integration,contract,replay,golden_data}`,
  `docs/{adr,strategy-specifications,runbooks}`.
- Toolchain: Python 3.13 via `uv`, `pyproject.toml` with Ruff + mypy + pytest
  configured. See [DECISIONS.md](DECISIONS.md).
- `Settings` (pydantic-settings) that fails closed if trading mode / broker
  environment / live-trading-compiled would ever permit live trading.
- Minimal FastAPI app (`forex_agent.apps.api.main:app`) with a `/health`
  endpoint that reports trading mode and broker environment.
- Async SQLAlchemy engine/session factory and declarative `Base`.
- Alembic wired to the same `Settings.database_url`. First migration
  (`06755c32d64c`) enables the `pgcrypto` extension; verified up/down/up
  end-to-end against live Postgres.
- `UUIDPrimaryKeyMixin` and `TimestampMixin`
  (`forex_agent.infrastructure.db.mixins`) — the PK and timestamp
  conventions every future table inherits. Covered by an integration test
  (`tests/integration/test_db_mixins.py`) against a throwaway table, proving
  server-generated UUIDs and tz-aware `TIMESTAMPTZ` round-trip correctly.
- `docker-compose.yml` for local PostgreSQL.
- Pre-commit hooks (ruff, mypy, hygiene, secret detection) and a GitHub
  Actions CI workflow (lint, type-check, pytest against a Postgres service
  container).
- Domain primitives (`forex_agent.domain`): `Instrument`, `Price` (bid/ask,
  with `entry_price`/`exit_price` per `TradeSide`), `Units`, `Money`,
  `UtcTimestamp` — all `Decimal`-based, all immutable, zero dependency on
  FastAPI/SQLAlchemy/OANDA/HTTP clients/environment variables. That boundary
  is enforced by an automated contract test
  (`tests/contract/test_domain_boundary.py`), not just review discipline.
- `BrokerPort` (`forex_agent.application.ports.broker_port`): a `Protocol`
  for broker connectivity — `get_price`/`get_account_balance` only, no
  order placement (out of scope until Risk Engine/Paper Trading Execution
  is assigned). A typed exception hierarchy
  (`application/ports/exceptions.py`) and an in-memory
  `FakeBrokerPort` (`tests/fakes/broker_port.py`) exist so anything
  depending on this port is testable before FX-4's real OANDA adapter
  lands. Same import-boundary enforcement as domain, via
  `tests/contract/test_application_boundary.py`.
- `OandaBrokerAdapter` (`forex_agent.infrastructure.broker_oanda`): the real
  `BrokerPort` implementation against OANDA's v20 REST practice API, via
  `httpx`. Refuses to operate against anything but the practice host.
  Verified against both a mocked HTTP transport (19 unit tests) and the
  real OANDA practice API (2 live integration tests, auto-skipped when
  OANDA credentials aren't configured — e.g. in CI). Note: these live
  tests are occasionally flaky when the full suite runs back-to-back
  (an intermittent 401 from OANDA) — they pass reliably in isolation.
  Root cause undetermined.
- A local `.env` with real OANDA practice credentials (gitignored, never
  committed) — connectivity confirmed working.
- `Granularity`, `Ohlc`, `Candle` domain value objects — bid *and* ask
  OHLC per candle (spread, per CLAUDE.md), `is_finalized` flag. `Candle`
  rejects crossed-market data (ask below bid at open or close). `Candle`
  also carries `source: CandleSource` (`NATIVE`/`AGGREGATED`, FX-24,
  defaults to `NATIVE`) — provenance, not just descriptive: see
  `candles` table below.
- `candles` table (migrations `91c1293c5760`, `635084cc3eb0`) with a
  unique constraint on `(instrument, granularity, start_time, source)`
  — `source` included since FX-24, so a native candle and a
  self-aggregated candle for the same logical slot can coexist in
  storage without colliding in an upsert. Plus `CandleRepository`
  (application port: `upsert_many`, `get_range`) and
  `SqlAlchemyCandleRepository` — idempotent upsert via Postgres
  `ON CONFLICT DO UPDATE`, internally batched into 1000-row statements
  (FX-27H) since asyncpg caps bound query parameters at 32767 and a full
  5000-candle page needs 70,000 unbatched — a real bug hit on the very
  first live backfill page while building the research dataset, fixed
  and regression-tested. `get_range` takes an explicit
  `source: CandleSource | None = None` (FX-27): `None` means "all
  sources" as a deliberate choice, never an implicit pick of whichever
  provenance happens to exist — pass `CandleSource.NATIVE`/`.AGGREGATED`
  to filter to one. `AggregateCandles` (below) uses this to read only
  `NATIVE` source candles, so re-aggregating already-`AGGREGATED` data
  can never happen silently.
- `MarketDataPort` (`get_candles`), separate from `BrokerPort`, implemented
  by `OandaMarketDataAdapter` against OANDA's `/v3/instruments/.../candles`
  endpoint (no account ID needed for this one). Bounded to what a single
  request can return (OANDA's own 5000-candle cap) — raises
  `CandleRangeTooLargeError` rather than silently truncating; pagination
  above this port is `BackfillCandles` (FX-26, below). Sends
  `dailyAlignment=17`/`alignmentTimezone=America/New_York` explicitly
  (FX-24, confirmed live to already match the practice API's own
  default) and tags every candle `source=NATIVE`.
- `candle_boundary.candle_start_boundary`/`candle_end_time`
  (`forex_agent.domain.candle_boundary`, FX-25H): the one canonical,
  DST-aware definition of "when does a candle of a given granularity
  starting at a given instant actually close" — `H2`/`H3`/`H4`/`H6`/
  `H8`/`H12`/`D` anchor to 17:00 `America/New_York` via `zoneinfo`
  (matching OANDA's own native candles, confirmed live); `H1` and finer
  use plain epoch-floor arithmetic (no DST ambiguity there). Extracted
  after FX-25 independently reimplemented (and got wrong, for the
  fall-back case) its own fixed-duration H4 assumption — both
  `aggregate_candles` and `MultiTimeframeTrendStrategy` now import from
  here rather than each computing candle duration their own way.
- `aggregate_candles` (`forex_agent.domain.candle_aggregation`, FX-7,
  day-aligned bucketing fixed FX-24, completeness check hardened
  FX-25H/FX-25H.1): buckets for day-aligned granularities are DST-aware
  via `candle_boundary`; `H1` and finer are unaffected. A bucket's
  "complete" check (FX-25H) is exact expected-source-start-time-sequence
  matching, not a member count — a member count couldn't distinguish a
  genuinely DST-short bucket from one merely missing data, nor catch a
  duplicate-plus-missing source candle at the right total count (the
  original FX-7 edge case, now closed by the same fix). That expected
  sequence is itself only valid (FX-25H.1) if the last source candle
  lands exactly on the target bucket's own end — nominal duration
  divisibility (e.g. `H6 % H3 == 0`) doesn't guarantee NY wall-clock
  source boundaries stay nested inside the target boundary across a DST
  discontinuity (reproduced directly: an `H3`-sourced `H6` bucket on the
  spring-forward day pulled in an hour of data from outside its own
  canonical end); a bucket whose sources straddle rather than tile it is
  dropped, not the granularity pairing generally. Every aggregated
  candle is tagged `source=AGGREGATED`; mixing `NATIVE` and `AGGREGATED`
  source candles in one call raises, same as mixing instruments or
  granularities.
- `IngestCandles` and `AggregateCandles` (`application/use_cases/`): the
  former wires `MarketDataPort.get_candles` to
  `CandleRepository.upsert_many`; the latter reads a range via
  `get_range(..., source=CandleSource.NATIVE)` (explicit since FX-27),
  aggregates via the pure `aggregate_candles` domain function, and
  upserts the result.
- `candle_pagination.split_into_pages` (`forex_agent.domain.
  candle_pagination`, FX-26): splits an arbitrarily large `[start, end)`
  into pages of at most `max_candles_per_page` candles, contiguous and
  non-overlapping by construction. DST-aware via `candle_boundary` for
  day-aligned granularities (a page's candle count can't be a fixed
  multiplication there, same reasoning as FX-25H/FX-25H.1); a
  closed-form fast path is used otherwise.
- `BackfillCandles` + `ingestion_watermarks` table/
  `IngestionWatermarkRepository` (`application/use_cases/
  backfill_candles.py`, FX-26): paginated, resumable historical backfill
  — the answer to `MarketDataPort`'s single-request bound. One watermark
  per `(instrument, granularity)` tracks a contiguous
  `[earliest_ingested, latest_ingested)` interval; the watermark *is*
  the resume state (no separate job/checkpoint object) — a later call
  naturally extends the frontier forward or backward without needing to
  remember an earlier request's own parameters. A disjoint request (no
  overlap or touch with existing coverage) raises rather than silently
  claiming an unfetched gap is covered. Backward-extension pages are
  fetched in descending order specifically so a crash never leaves a
  gap between newly-fetched data and pre-existing coverage. Verified
  against in-memory fakes for exhaustive branch coverage and against
  real Postgres for the core interruption/resume guarantee (a simulated
  mid-backfill failure, then a resumed call, completes without
  re-fetching or duplicating anything).
- Research dataset: `scripts/build_research_dataset.py` used
  `BackfillCandles` to populate real Postgres with 10 years (2016-09-19 to
  2026-09-19) of H1 and H4 candles for EUR/USD, GBP/USD, USD/JPY, USD/CAD,
  and XAU/USD — 385,689 candles total, all 10 `(instrument, granularity)`
  series backfilled in one run. XAU/USD needed no domain change (`XAU` is
  gold's real ISO 4217 code, and `Instrument` already accepts any
  3-letter uppercase code); confirmed available on the OANDA practice API
  before running. Surfaced FX-27H (above) — this was the backfill's first
  real run at full page size, and the very first page failed until that
  fix landed.
- Research dataset gap-check: `scripts/check_research_dataset_gaps.py`
  runs `DetectDataGaps` over every series' full backfilled range, then
  filters out the standard forex weekly closure (Friday 17:00–Sunday
  17:00 `America/New_York`, the same boundary FX-24 already anchors
  day-aligned candles to) before reporting anything as unexplained —
  `find_gaps`/`DetectDataGaps` are deliberately calendar-unaware (see
  below), so this filtering is the caller-side responsibility their own
  docs describe, kept in the script rather than added to domain code.
  Result: of 162,121 raw missing candle slots across all 10 series, 97%
  were ordinary weekly closures; the 5,826 remaining split into two
  explained categories, confirmed rather than assumed — the four FX
  pairs' residual (~420 H1/~100 H4 each) clusters on named calendar
  holidays (Christmas, New Year's, Thanksgiving) our weekly-only filter
  doesn't know about, and XAU_USD's much larger residual (3,524 H1/208
  H4) is dominated by a clean, regular daily gap at 17:00 NY on ordinary
  trading days — OANDA's daily settlement/rollover quote gap specific to
  how it quotes commodities (confirmed via a live re-fetch of one
  Thanksgiving-2016 window: OANDA itself returns no candles there, not a
  backfill bug) — plus a smaller scatter around metals-specific holiday
  early-closes (e.g. the day before Thanksgiving), also confirmed live.
  No scattered, unexplainable single-candle dropouts found anywhere.
  Surfaced FX-27H.1 (above) — the gap check's own first run had one
  false-positive "gap" per series, from `DetectDataGaps` itself, not the
  data; fixed before trusting the rest of the results.
- **Research dataset extended backward (FX-38 Part A/B)**:
  `scripts/discover_historical_coverage.py` (new) binary-searches each
  series' true earliest OANDA candle rather than assuming one;
  `scripts/extend_research_dataset_pre2016.py` (new) backfills to it via
  the same unmodified `BackfillCandles`. Actual earliest H1 candle: the
  four FX pairs 2002-05-06/07 (not materially different from each
  other), XAU/USD 2006-03-19 (genuinely, not artificially, ~4 years
  later). +376,748 candles total. The four FX pairs' opening stretch is
  real but sparse (~5% of normal density through 2004, dense from
  ~2005) — disclosed, not excluded. **XAU_USD's originally-reported
  "~15% through 2006" figure was a measurement artifact, corrected by
  FX-38H**: it was an average over a fixed calendar window that mostly
  predated XAU_USD's data even existing, not real sparsity — XAU_USD's
  data is already near-full density from its very first available
  candle. Coverage now spans each instrument's own true earliest-
  available candle through the present. Full discovery/extension/gap-
  check tables are in `docs/DECISIONS.md`'s FX-38 entries; the density
  correction and the objective usable-history-start algorithm that
  found it are in FX-38H's own entry.
- **Pre-development historical holdout evaluation (FX-38 Parts D-G,
  then re-run and hardened by FX-38H — both complete)**:
  `EmaCrossoverStrategy`, `EmaCrossoverTrendRegimeGatedStrategy`,
  `MultiTimeframeTrendStrategy`, and `CloseChannelBreakoutStrategy` —
  all with their existing default parameters, unchanged throughout —
  evaluated separately on the already-inspected 2016-2026 development
  window and a pre-2016 historical holdout. FX-38's own first pass
  used the raw technical earliest-available candle and a single
  continuous run sliced by `entry_time`; external review found two
  real methodological gaps (no objective usable-history threshold, and
  a possible boundary-straddling trade leak), both fixed by FX-38H:
  holdout now starts at each series' own objectively-determined
  `earliest_usable_research_candle`, and every window (both
  development AND holdout) is economically sealed (`domain.sealed_
  window_backtest`) — no trade's entry or exit price can come from
  outside its own window. **The finding survives, on firmer ground**:
  none of the story's four candidate combinations (`USD_JPY`/`XAU_USD`
  × `CloseChannelBreakoutStrategy`/`MultiTimeframeTrendStrategy`) flip
  sign between periods under either methodology; two comparison
  strategies on the same two instruments (`EmaCrossoverStrategy` on
  USD_JPY, `EmaCrossoverTrendRegimeGatedStrategy` on XAU_USD) DO
  sign-flip, unchanged by the more rigorous rerun. A direct audit found
  FX-38's original boundary-straddling exposure real but numerically
  negligible (at most 1 straddling trade per combination, out of
  hundreds to thousands). Time-stability slicing (2-year and yearly,
  USD_JPY/XAU_USD, all four strategies) found the apparent trend/
  breakout pattern predates 2016, and — corrected by FX-38H after an
  overstated first version — found `2024-2025` specifically (not
  "2022-2025" as a pair) near-best in 7 of 8 series studied, plus one
  clear "one exceptional episode" case (XAU_USD's ADX-gated EMA
  leaning heavily on 2020-2021 alone). No strategy in this story is
  described as validated; the natural next question (statistical
  significance of the ~1.05-1.18 holdout profit factors, accounting
  for trade dependence and regime clustering) is open, not pursued
  here. Full results, the four-combination comparison table showing
  exactly what changed between FX-38 and FX-38H and why, the
  boundary-straddling audit, and the corrected time-stability
  conclusion are in `docs/DECISIONS.md`'s FX-38/FX-38H entries. The
  actual analysis programs are committed
  (`scripts/determine_usable_history_start.py`, `scripts/run_fx38h_
  analysis.py`) alongside a machine-readable artifact
  (`research_results/fx38h/results.json`).
  **FX-38H.1** (external review of FX-38H itself, complete): closed the
  last methodological gap — holdout warm-up could previously reach
  slightly before a series' own `earliest_usable_research_candle`
  (fixed: bounded below by it, per-series, independently for
  `MultiTimeframeTrendStrategy`'s H1/H4), and every candle fetch now
  explicitly requests `CandleSource.NATIVE` rather than relying on
  `source=None`'s "any provenance" default. Rerun confirmed the effect
  is exactly as small as expected: XAU_USD's two candidates are
  bit-for-bit identical (no pre-existing data there to have leaked in
  the first place), USD_JPY's shift by ~0.001 PF. No result changes
  materially; no sign flips created or removed.
- **FX-39: block-bootstrap statistical significance testing (complete)
  — this closes the pure-technical-strategy research phase.**
  `domain/block_bootstrap.py` (new): moving-block bootstrap (Künsch
  1989, block length chosen objectively from each series' own sample
  autocorrelation function) as the primary significance test, plus a
  regime (2-year block) bootstrap as an explicitly-labeled secondary
  ROBUSTNESS check (not an equally-precise significance test — only
  ~6 source blocks per holdout), Holm-Bonferroni correction across the
  four FX-38H candidates, and preregistered interpretation tiers, all
  locked before any real result existed. Applied to the four holdout
  candidates plus two negative controls (`scripts/run_fx39_
  significance_testing.py`, `research_results/fx39/results.json`).
  **Result: none of the four candidates are statistically
  distinguishable from noise** — approximate percentile-bootstrap
  one-sided p-values 0.13-0.19, Holm-adjusted p=0.53 for all four,
  nowhere near significance. Three of the four selected `block_length
  =1` (no detectable autocorrelation — an ordinary, non-block
  bootstrap for those three); only USD_JPY/`MultiTimeframeTrendStrategy`
  selected a larger block (3). One nuance: XAU_USD/
  `MultiTimeframeTrendStrategy`'s regime-block CI barely excludes zero,
  but that is the secondary robustness check (only 6 blocks), not read
  as overriding the primary result. The two negative controls also
  failed to reach significance in the negative direction — not a
  method failure (verified separately on synthetic data). Given the
  observed effect sizes, variability, and available holdout samples,
  neither the positive candidates nor the negative controls are
  distinguishable from zero. FX-38/FX-38H's own findings (no sign
  flips, directional consistency) stand unchanged — FX-39 recalibrates
  confidence, it doesn't overturn them.
  Per this story's own locked, unconditional prohibition: no parameter,
  strategy, instrument, or period was changed in response to this
  result. Full tables in `docs/DECISIONS.md`'s FX-39 entries.
- **FX-40: backtest run report export + static HTML results viewer
  (complete)**. Observability/reporting only — no strategy behavior
  changed, `domain/backtest.py`/`trade_simulation.py`/`backtest_
  metrics.py` untouched, no new dependency. `domain/backtest_report.py`
  (new): a pure serializer (`to_report_dict`, no file/DB/network I/O,
  no metric recomputation) turning an already-computed `list[
  SimulatedTrade]` + `BacktestMetrics | None` into the canonical report
  schema — every `Decimal`-derived value (prices, `Money` amounts,
  ratios, `Decimal`-typed strategy parameters) as a JSON string, plain
  integers as JSON integers, mathematically undefined metrics as JSON
  `null` (never fabricated). `scripts/export_backtest_report.py` (new)
  composes the existing, unmodified `get_range(...,
  source=CandleSource.NATIVE)` → `run_backtest`/`run_backtest_
  incremental` → `simulate_trades` → `compute_metrics` → `to_report_
  dict` pipeline for a small explicit mapping of 7 concrete strategies
  (not a general plugin architecture), writing `reports/<name>.json` +
  idempotently maintaining `reports/index.json` (atomic write) +
  regenerating `reports/dashboard_data.js`. `fta_dashboard_sketch.html`
  (new, repo root): a single static file, no ES modules/npm/server —
  loads `dashboard_data.js` via a classic `<script src>` tag (works
  under `file://`, where `fetch()` of local files is commonly blocked),
  shows all required metrics (with explicit "N/A" for null fields, not
  fabricated zeros), a `<canvas>`-drawn equity curve (native browser
  API, no charting library), a trade table, a run selector for multiple
  reports, and explicit empty/zero-trade states. Verified against three
  real exported runs (`ema_crossover_v1`, `close_channel_breakout_v1`
  with a non-default parameter override, `multi_timeframe_trend_v1`
  exercising the H4-dependent path); `reports/` is committed alongside
  the code. Full details in `docs/DECISIONS.md`'s FX-40 entry.
- **FX-41: point-in-time fundamental data model (complete)**.
  Architecture/foundation only — no external provider, no ingestion
  pipeline, no strategy, no score, no decision logic. `domain/
  macro_series_definition.py` (new): `MacroSeriesDefinition` frozen
  dataclass (`key`, `economy`, `currency`, `category`, `unit`,
  `frequency`, `point_in_time_safety`) — canonical, provider-independent
  series identity; no FRED/central-bank/vendor ID anywhere in it. Not
  persisted in its own table — kept a pure in-memory value object (see
  `docs/DECISIONS.md`). Also carries `require_point_in_time_safe`, a
  fail-closed guard raising unless a series is classified
  `PointInTimeSafety.POINT_IN_TIME_SAFE` (defaults to `UNKNOWN`, not
  safe). `domain/macro_observation_vintage.py` (new):
  `MacroObservationVintage` frozen dataclass — one immutable
  point-in-time-safe fact per revision, with `observation_period`,
  `released_at`, and optional `effective_at` kept explicitly distinct
  (never collapsed); `value` is `Decimal`-only; a revision is a new
  instance with a later `released_at` and higher `revision_sequence`,
  never a mutation. `domain/macro_category.py`/`macro_frequency.py`/
  `point_in_time_safety.py` (new): small closed enums
  (`MacroCategory`, `MacroFrequency`, `PointInTimeSafety`).
  `application/ports/macro_observation_repository.py` (new):
  `MacroObservationRepository` Protocol — `add_vintage` (write, never
  overwrites), `latest_available_as_of`/`observation_as_known_at`
  (point-in-time reads); the invariant "a query at T cannot return a
  vintage whose `released_at` is after T" is the entire contract.
  `infrastructure/db/models/macro_observation_vintage.py` +
  `infrastructure/db/macro_observation_repository.py` (new):
  `MacroObservationVintageRow`/`SqlAlchemyMacroObservationRepository` —
  every write is `INSERT ... ON CONFLICT DO NOTHING` keyed on
  `(series_key, observation_period, revision_sequence)`, so no
  application code path ever issues an UPDATE against a historical
  vintage row; both read methods filter `released_at <= as_of` before
  ordering. Migration `7f04ea660a34` (new table, composite unique
  constraint, `(series_key, released_at)` index). Tests cover the
  story's exact worked examples (February CPI released March 12 13:30
  UTC; revision 2.1→2.4 between July 1/August 1 with as-of queries at
  July 15/August 15), an explicit no-future-leakage test, Decimal
  fidelity, and naive-timestamp rejection — against both a
  `FakeMacroObservationRepository` and live Postgres; the `released_at`
  filter was deliberately removed and confirmed to fail these tests
  before being restored. Full details in `docs/DECISIONS.md`'s FX-41
  entry.
- **FX-41H: macro vintage integrity hardening (complete)**. `add_vintage`
  now raises `MacroVintageConflictError` (new, `application/ports/
  macro_observation_repository.py`) when a vintage with the same
  `(series_key, observation_period, revision_sequence)` identity
  already exists with a different `value`/`released_at`/`effective_at`/
  `source` — an exact duplicate retry remains a no-op (idempotent), but
  a same-identity/different-payload write is now a caught
  data-integrity error rather than a silent drop. Implemented
  identically in `SqlAlchemyMacroObservationRepository` (via `INSERT
  ... ON CONFLICT DO NOTHING RETURNING id`, then a comparison fetch on
  conflict) and `FakeMacroObservationRepository`. `latest_available_as_
  of`/`observation_as_known_at` both gained `revision_sequence DESC` as
  a final ORDER BY tie-breaker after `released_at DESC`, so two
  vintages sharing an identical `released_at` resolve deterministically
  to the higher revision rather than to scan order. 14 new tests (exact
  duplicate, conflicting value/released_at/effective_at/source, the
  stored row's survival after a conflict, the exception's existing/
  incoming payload, the tie-break scenario) against both the fake and
  live Postgres; conflict detection and the tie-breaker were each
  deliberately removed and confirmed to fail the relevant tests before
  being restored. No point-in-time semantics changed. Full details in
  `docs/DECISIONS.md`'s FX-41H entry.
- **FX-42: canonical central-bank policy-rate registry (complete;
  corrected by FX-42H/FX-42H.1 below — this bullet describes the
  CURRENT, post-hardening state)**. Semantics and provider mappings
  only, no persistence, no ingestion, no strategy. `domain/
  rate_transformation.py`: `RateTransformation` (`RateTransformationKind`
  `IDENTITY`/`TARGET_RANGE_MIDPOINT` + an explicit `version` string) with
  a real `apply(*raw_values) -> Decimal` method. `domain/
  provider_series_mapping.py`: `ProviderSeriesMapping` (`provider`,
  `provider_series_ids` tuple, `point_in_time_safety`, `verified: bool`,
  `notes`) — the explicit canonical-identity-vs-provider-mapping split
  FX-41 deferred, and (since FX-42H) the SOLE place point-in-time safety
  is tracked at all (`MacroSeriesDefinition` no longer has its own
  `point_in_time_safety` field — see the FX-42H bullet below). `domain/
  policy_rate_definition.py`: `PolicyRateDefinition` (one effective-dated
  definition — `series`, `institution`, `instrument_name`,
  `transformation`, half-open `valid_from`/`valid_to` with `covers()`,
  non-empty `provider_mappings`); `summary()` answers the six required
  audit questions. `domain/declared_policy_rate_gap.py` (FX-42H.1, new):
  `DeclaredPolicyRateGap` (`currency`, half-open `start`/`end`, required
  non-empty `reason`) — every gap between consecutive definitions for a
  currency must now be explicitly declared with matching boundaries, or
  registry validation fails; a declared gap must not overlap an actual
  definition or another declared gap. `domain/policy_rate_registry.py`:
  `POLICY_RATE_DEFINITIONS` — eleven definitions covering USD, EUR, GBP,
  JPY, CAD (JPY needs six to represent its genuine operational-regime
  history, plus two declared gaps in `DECLARED_GAPS` — see FX-42H.1).
  USD is split into two effective-dated eras sharing one
  `USD_POLICY_RATE` series key (single target point, FRED `DFEDTAR`,
  February 4 1994 through December 16, 2008; target range midpoint, FRED
  `DFEDTARU`/`DFEDTARL`, from then on) — the story's required
  effective-dated/transformed example. `definition_as_of`/
  `definitions_for_currency`/`canonical_series_for_currency` provide
  point-in-time definition lookup; `validate_registry` enforces
  registry-wide invariants (identical `MacroSeriesDefinition` semantics
  per currency, non-overlapping validity windows, every gap explicitly
  declared with matching boundaries, declared gaps not overlapping
  definitions or each other, all five required currencies present) at
  import time. No date or provider series ID is confirmed against a live
  provider — see `docs/DECISIONS.md`'s FX-42/FX-42H/FX-42H.1 entries for
  exactly what FX-43 still needs to verify.
- **FX-42H: policy-rate registry semantic hardening (complete)**.
  Corrects FX-42's factual/semantic weaknesses before FX-43 ingestion,
  without changing FX-42's domain architecture. (1) Removed
  `MacroSeriesDefinition.point_in_time_safety`/`require_point_in_time_
  safe` entirely (FX-41) — a canonical concept has no source of its own
  to classify. (2) Replaced `require_point_in_time_safe_mapping` with
  `require_research_usable_mapping`, which fails closed unless a mapping
  is BOTH `verified` AND `POINT_IN_TIME_SAFE` — every mapping in the
  registry still fails this guard, by design. (3) USD's target-point era
  now starts 1994-02-04 (first FOMC meeting with immediate, explicit
  policy announcements), not 1954 — the earlier `DFEDTAR` history is
  documented as a retrospective reconstruction, not point-in-time-safe.
  (4) EUR's canonical scalar is now the ECB MRO minimum-bid/fixed rate
  (`FM.D.U2.EUR.4F.KR.MRR_RT.LEV`), not the Deposit Facility Rate
  continuously — DFR is documented as a candidate future regime-aware
  feature, explicitly not to be silently substituted back in. (5) JPY no
  longer claims one continuous definition: five distinct rate-target eras
  (overnight-call-rate target ×2, the 2016-2024 policy-rate-balance
  regime, the transitional March-July 2024 0-0.1% range, and the current
  single-point-target era) with INTENTIONAL GAPS during the two
  quantitative-easing eras (2001-2006, 2013-2016) where the BoJ's
  operating target was a quantity, not a rate — `definition_as_of`
  correctly returns `None` for any instant in either gap. (6)
  `validate_registry` now allows gaps (previously rejected) and checks
  full `MacroSeriesDefinition` equality per currency, not just the same
  `key` string. (7) CAD's overnight-target boundary now starts
  1999-02-01, not 1991-02-01, with provider ID `V39079` replacing the
  placeholder. BoJ mapping remains entirely unresolved (five
  `VERIFY_BOJ_...` placeholders) — this story explicitly does not
  attempt to resolve it. 24 net new/changed tests (875 total),
  including both JPY quantitative-easing gaps, the combined guard's
  four failure/success paths, a canonical-series-metadata-mismatch
  rejection, and the corrected USD/EUR/CAD boundaries. Regression-proof
  discipline applied to the combined guard, the stricter series-equality
  check, and the gap-tolerance removal — each deliberately reverted,
  confirmed to fail (the gap-tolerance revert made the real registry
  fail to IMPORT, not just fail a test, since JPY's own gaps trip the
  old check), then restored. Full details in `docs/DECISIONS.md`'s
  FX-42H entry.
- **FX-42H.1: policy-rate gap and JPY boundary hardening (complete)**.
  Replaces FX-42H's blanket gap tolerance with explicitly declared,
  auditable gaps, and corrects two further JPY factual weaknesses.
  `domain/declared_policy_rate_gap.py` (new): `DeclaredPolicyRateGap`
  (`currency`, half-open `start`/`end`, required non-empty `reason`).
  `validate_registry` now rejects any undeclared gap between consecutive
  definitions (even a deliberately-constructed one-day gap), rejects a
  declared gap that overlaps an actual definition, and rejects declared
  gaps that overlap each other — `DECLARED_GAPS` holds the registry's
  two real gaps (both JPY). JPY's 2006-2013 overnight-call-rate era is
  split at October 5, 2010 (`_JPY_CALL_RATE_ERA_2A`/`_2B`): the BoJ
  explicitly changed its target from a single point (~0.1%) to a range
  (~0-0.1%) under "Comprehensive Monetary Easing", now represented with
  `TARGET_RANGE_MIDPOINT` from that date, matching how the registry
  already treats USD and JPY's 2024 transitional range. JPY's
  Policy-Rate Balance era now starts February 16, 2016 (the -0.10%
  rate's EFFECTIVE date) rather than January 29, 2016 (its
  ANNOUNCEMENT/release date) — the preceding QQE declared gap is
  extended to match; the definition's `notes` tie this directly to
  FX-41's `MacroObservationVintage.released_at`/`effective_at`
  distinction for FX-43. Also corrected a stale `PolicyRateDefinition`
  docstring that still described JPY as needing only one continuous
  definition (true for EUR/GBP/CAD, wrong for JPY/USD since FX-42H
  itself split them). 24 net new/changed tests (899 total), including
  the undeclared one-day-gap rejection, each declared JPY gap's
  boundaries, definition/gap and gap/gap overlap rejection, the exact
  2010-10-04/2010-10-05 transformation-kind boundary, the 0/0.1 midpoint
  arithmetic, and the exact 2016-02-15/2016-02-16 boundary.
  Regression-proof discipline applied to the undeclared-gap,
  gap-overlaps-definition, and gap-overlaps-gap checks (each disabled in
  turn), and to the real registry's 2010-10-05 transformation split and
  2016-02-16 boundary (each reverted in turn) — every case confirmed to
  fail the relevant test(s) before being restored. Full details in
  `docs/DECISIONS.md`'s FX-42H.1 entry.
- **FX-43: first real external fundamental data — policy-rate backfill
  (complete)**. The first use case/infrastructure in this codebase
  that ingest real external fundamental data. `domain/
  policy_rate_change_extraction.py` (new): `extract_change_points`,
  pure — reduces a provider's raw daily series (which repeats the same
  value every day it stayed in effect) down to genuine change points
  only, one `MacroObservationVintage` per date the canonical value
  actually moved; a date missing from one input series (needed only
  for `TARGET_RANGE_MIDPOINT`) is skipped and reported, never
  fabricated. `application/ports/policy_rate_history_provider.py`
  (new): `PolicyRateHistoryProvider`, a minimal fetch-only port.
  `application/use_cases/backfill_policy_rate_history.py` (new):
  `BackfillPolicyRateHistory` — orchestrates registry → provider →
  change extraction → `MacroObservationRepository.add_vintage`
  (FX-41H's existing idempotent conflict handling, no new mechanism
  added); produces a `CurrencyBackfillReport`/`EraBackfillReport` with
  per-era change-point/vintage/skipped-date/conflict counts, actual
  (not merely requested) coverage span, and explicit
  `unconfigured_eras`/`fetch_error` reporting rather than silent
  skips. `infrastructure/policy_rate_providers/` (new): four adapters
  — FRED, ECB Data Portal, Bank of England, Bank of Canada — all
  confirmed live against their real public APIs (no API key needed for
  any of them). `scripts/backfill_policy_rate_history.py` (new): runs
  the real backfill against live Postgres, writes
  `reports/policy_rate_backfill_report.json`.
  Live verification found and fixed two real bugs: the ECB client
  double-prefixed the dataflow ID in its request path (the registry's
  key already includes "FM."), and the coverage report originally
  showed the requested window rather than the actual data span
  (exposed by CAD's genuine coverage gap). Also found and fixed: the
  Bank of England's WAF blocks httpx's default `User-Agent`. USD
  (FRED)/EUR (ECB, `MRR_RT` confirmed correct)/GBP (BoE)/CAD (BoC, but
  only from 2009-04-21 — 1999-02-01 through 2009-04-20 has no daily
  target-rate source available and is explicitly NOT backfilled) are
  all marked `verified=True`; JPY is not attempted (still unresolved,
  per FX-42H.1). 258 real `MacroObservationVintage` rows now in
  Postgres (USD 92, EUR 62, GBP 71, CAD 33), spot-checked against known
  historical facts (e.g. USD's Dec 16 2008 vintage is exactly `0.125`,
  the FOMC's 0-0.25% target range midpoint) and proven to answer
  as-of queries correctly across a real historical transition. The
  backfill script was run twice live with identical results and zero
  conflicts, confirming idempotency against real data, not just fakes.
  `released_at` is set to each vintage's effective date (a proxy, not
  a verified announcement timestamp) — no `ProviderSeriesMapping` is
  promoted to `PointInTimeSafety.POINT_IN_TIME_SAFE`, and
  `require_research_usable_mapping` still rejects every mapping in the
  registry; establishing genuine announcement timestamps is explicitly
  deferred as this story's own named "next review gate." Full details
  in `docs/DECISIONS.md`'s FX-43 entry.
- **FX-43H: policy-rate backfill hardening (complete)**. Hardens FX-43
  before any rate-differential research reads this data. (1) Registry
  validity is `[valid_from, valid_to)`, but provider APIs are queried
  by inclusive calendar-date range —
  `BackfillPolicyRateHistory._fetch_end` now clamps an era's requested
  end to `valid_to - 1 day` whenever the window would otherwise reach
  the next era's start, rather than relying on a provider's own
  behavior (e.g. FRED's `DFEDTAR` happening to stop the day before).
  (2) `EraBackfillReport` now tracks `earliest_raw_observation`/
  `latest_raw_observation` separately from `earliest_change_point`/
  `latest_change_point`; `CurrencyBackfillReport.coverage_start`/
  `coverage_end` aggregate from the RAW fields, so a stable rate that
  stops changing but keeps being published daily correctly reports
  coverage extending to the present, not to its last change. (3)
  `VintageWriteOutcome` (`INSERTED`/`ALREADY_PRESENT`) replaces
  `add_vintage`'s `None` return across the Protocol and both
  implementations; `BackfillPolicyRateHistory` reports
  `vintages_inserted`/`vintages_already_present` accurately —
  confirmed against real Postgres: cleared data, first run
  inserted=258/already_present=0, second run inserted=0/
  already_present=258, zero duplicate rows. (4)
  `MacroObservationVintage` gained `released_at_is_verified: bool =
  True`; every backfilled vintage is now explicitly stored with
  `released_at_is_verified=False`. `MacroObservationRepository` gained
  `replace_provisional_release_timing` — the one deliberate,
  narrowly-scoped UPDATE in the SQL repository, correcting only
  `released_at`/`effective_at`/`released_at_is_verified` on an
  existing PROVISIONAL row (never `value` or `revision_sequence` — a
  release-timing correction is never a revision), refusing if the row
  is already verified. No caller exists yet — this story's job was to
  make replacement possible and safe, not to perform it. New migration
  `5707ecb39242`. (5) `extract_change_points` now raises the new
  `ConflictingRawObservationError` when one raw series reports two
  DIFFERENT values for the same date (an identical repeat still
  collapses harmlessly); the use case reports this as an explicit
  `data_integrity_error`, never "last value wins". (6) Corrected FRED
  documentation that wrongly said `DFEDTAR` "covers 1954-present" — it
  is FRED's DISCONTINUED single-target-rate series, ending 2008-12-15.
  New tests include the story's own exact half-open-boundary scenario
  (era A's `valid_to` and era B's `valid_from` both 2008-12-16, both
  providers given a row on that date, proven to belong only to era B).
  Regression-proof discipline applied to the boundary clamp and the
  raw-vs-change-point coverage aggregation (each reverted, confirmed
  to fail its dedicated test, restored). 962 tests pass (full suite,
  up from 942). Full details in `docs/DECISIONS.md`'s FX-43H entry.
- **FX-43H.1: provisional timestamp fail-closed hardening (complete)**.
  Hardens FX-43H's own `released_at_is_verified`/
  `replace_provisional_release_timing` mechanisms themselves — no new
  provider, no verified announcement timestamp. (1)
  `released_at_is_verified` now DEFAULTS to `False` (was `True`) at
  both the domain (`MacroObservationVintage`) and SQLAlchemy-model
  layers — a caller must explicitly pass `released_at_is_verified=
  True` to claim verification. (2) Migration `80c0ae20257b` changes
  the column's `server_default` to `'false'` AND unconditionally
  reclassifies every pre-existing row to `False` in the same
  migration — a schema-default change alone would not retroactively
  fix rows already written under the old default, and this codebase
  does not rely on manually clearing/reloading the database to reach
  a correct state; confirmed against real Postgres (all 258 rows
  already `False` from FX-43H's own explicit sets, so this ran as a
  structural safety net, not a live correction). (3)
  `replace_provisional_release_timing` in
  `SqlAlchemyMacroObservationRepository` is now a single atomic
  conditional `UPDATE ... WHERE ... AND released_at_is_verified =
  false ... RETURNING id`, replacing the old SELECT-then-UPDATE — the
  provisional-row check and the write are one statement, so two
  concurrent replacement attempts against the same identity cannot
  both succeed. New concurrency regression test
  (`test_concurrent_replace_provisional_release_timing_only_one_wins`)
  races two independent sessions via `asyncio.gather`; a new migration
  unit test (`tests/unit/infrastructure/
  test_migration_released_at_is_verified_fail_closed.py`) asserts the
  migration's exact DDL/DML by patching `alembic.op` directly, without
  a real database. Regression-proof discipline applied to all three
  new guarantees (domain default, atomic UPDATE, migration
  reclassification) — each deliberately reverted, confirmed to fail
  its dedicated test for the right reason (the reverted atomic UPDATE
  failed with both racing attempts reporting success), then restored.
  967 tests pass (full suite, up from 962). Full details in
  `docs/DECISIONS.md`'s FX-43H.1 entry.
- **FX-44: point-in-time policy-rate release verification (complete)**.
  The first real use of FX-43H/FX-43H.1's replacement mechanism —
  cited, researched release-timing rules applied to USD/EUR/GBP/CAD's
  258 real change points (JPY stays out of scope). New
  `domain.release_timing_rule.ReleaseTimingRule` (institution, local
  time-of-day, IANA timezone, validity window, citation, and a
  `ReleaseTimingConfidence` of `EXACT` or `CONSERVATIVE_SAFE_BOUND` —
  a deliberately late, safe-but-inexact bound, used only where the
  exact minute isn't confidently citable) converts a local date to an
  exact UTC instant via `zoneinfo` (correct historical DST offset per
  date, zero hand-coded transition dates). New
  `domain.policy_rate_release_timing_registry` applies these rules
  currency-by-currency, ONLY to change points confirmed to be regular
  scheduled decisions — known irregular/inter-meeting/emergency dates
  and under-researched eras are explicitly left `UnresolvedTiming`,
  never guessed. EUR's registry entry models a genuine, documented
  announcement-before-effective-date split (confirmed computationally:
  every relevant stored EUR date is a Wednesday, matching the ECB's
  own "first operation following the decision" methodology) —
  `released_at` moves to the earlier Thursday decision date/time,
  `effective_at` keeps the later, original stored date. New
  `MacroObservationVintage.released_at_is_conservative_bound: bool =
  False` field (migration `aee1fa641be6`) keeps the conservative
  outcome structurally distinct from `released_at_is_verified=True` —
  never overloaded to mean "we guessed a safely late time".
  `replace_provisional_release_timing`'s atomic UPDATE predicate now
  requires BOTH outcome flags `False` before either can be written,
  and takes a `confidence` parameter deciding which one gets set. New
  `application.use_cases.verify_policy_rate_release_timing.
  VerifyPolicyRateReleaseTiming` — the first real caller of `replace_
  provisional_release_timing` — resolves each stored change point via
  the registry, replaces a still-provisional row, leaves an unresolved
  one untouched, and for an ALREADY-classified row compares against
  what the registry resolves to now (identical timing → no-op,
  mismatch → explicit `CONFLICTING`, never silently overwritten);
  idempotent by construction. New `domain.research_readiness.
  require_research_ready_interval` — FX-44's critical invariant as
  code and the mandatory FX-45 pre-flight check — fails closed if ANY
  vintage in a selected interval is neither verified nor
  conservative-bound safe; a single provisional observation fails the
  whole interval. No `ProviderSeriesMapping` is promoted to
  `POINT_IN_TIME_SAFE` for any currency (none has zero unresolved
  change points across its full history); interval-specific safety is
  represented explicitly instead, in `research_results/fx44/
  policy_rate_release_verification.json`
  (`scripts/verify_policy_rate_release_timing.py`). Live run against
  real Postgres: USD 30 exact/54 conservative/8 unresolved (of 92);
  EUR 44/0/18 (of 62); GBP 65/0/6 (of 71); CAD 0/30/3 (of 33); zero
  conflicts; a second run reproduced identical figures with zero
  newly-classified (idempotency confirmed live). Regression-proof
  discipline applied to every new safety-relevant mechanism (domain
  default, DST-sensitive UTC conversion, research-readiness fail-
  closed gate, the new conservative-bound atomic-UPDATE predicate, and
  the use case's idempotency match-check) — each deliberately broken,
  confirmed to fail its dedicated test for the right reason, then
  restored. 1023 tests pass (full suite, up from 967). Full details in
  `docs/DECISIONS.md`'s FX-44 entry.
- **FX-44H: release-timing semantic hardening (complete)**. Fixes one
  real bug FX-44 shipped plus four related structural gaps. (1) USD's
  modern (2013+) EXACT tier previously conflated FRED's stored
  change-point date with the FOMC announcement date and set
  `effective_at=None` — wrong: that date is the operational EFFECTIVE
  date, per the FOMC's own "Implementation Note" mechanism. All 30
  currently-EXACT USD change points were individually cross-referenced
  against the Fed's own published meeting calendars — not a blind
  `-1 day` formula, which this exercise proved would have been wrong
  for 2 of the 30 (2015-12-16 "liftoff" and 2016-12-14 have a same-day
  gap, not +1). New `USD_EFFECTIVE_TO_DECISION_DATE`
  (`domain.policy_rate_release_timing_registry`) is an explicit,
  individually-cited `dict[date, date]` with NO formulaic fallback — a
  USD date not present as a mapping key is unresolved, even a future
  one. (2) New `MacroObservationRepository.correct_verified_release_
  timing` (port + both implementations) — a deliberately SEPARATE
  atomic UPDATE from `replace_provisional_release_timing`, with the
  opposite precondition (`released_at_is_verified = true`) plus an
  optimistic-concurrency guard on the caller's expected current
  values, proven safe under real concurrent correction attempts by a
  new `asyncio.gather` regression test. New `application.use_cases.
  remediate_release_timing.RemediateReleaseTiming` — a separate,
  deliberately-invoked use case (never automatic) that compares every
  currently-EXACT vintage against the registry's current resolution
  and corrects mismatches; idempotent by construction.
  `scripts/remediate_usd_release_timing.py` ran this live: all 30 USD
  rows corrected on the first run, zero writes (`ALREADY_CORRECT`) on
  an immediate second run — confirmed via direct SQL, including the
  story's own worked example (`2026-09-17` now reads
  `released_at=2026-09-16T18:00:00Z`,
  `effective_at=2026-09-17T00:00:00Z`), zero duplicate rows, zero
  remaining `CONFLICTING` change points across all four currencies. (3)
  `require_research_ready_interval` previously judged only in-interval
  vintages — insufficient, since a point-in-time query anywhere in an
  interval with zero in-interval changes still returns whatever
  vintage was carried in from before it. New `domain.research_
  readiness.select_research_candidates` derives BOTH the carry-in
  state and in-interval observations from a series' COMPLETE stored
  history, so a caller cannot hand-select the wrong candidates;
  `require_research_ready_interval`'s signature now takes that
  complete history directly, and an entirely empty derived candidate
  set fails closed too (`no_baseline` on `ResearchIntervalNotReadyError`
  ) rather than vacuously passing. New regression using a
  2008-01-22-like unresolved carry-in with a February interval
  containing no changes of its own, proven to fail. (4) Exact/
  conservative mutual exclusivity is now structurally enforced at both
  the domain layer (`MacroObservationVintage.__post_init__`) and the
  persistence layer (migration `f350d505412b`'s new CHECK constraint,
  confirmed live via a raw `UPDATE` correctly rejected with
  `IntegrityError`). (5) ECB citations now point to the ECB's own
  official 27 June 2022 press release (replacing a tweet and a news
  aggregator); `_resolve_eur` now structurally requires `stored_date.
  weekday() == Wednesday` before applying its six-day transformation —
  previously dependent entirely on a hand-curated exclusion list —
  with a new, empty-today `EUR_EXPLICIT_DECISION_DATE_OVERRIDES` as
  the only sanctioned escape hatch. Regression-proof discipline applied
  to every new mechanism except the CHECK constraint's own drop/
  recreate (correctly blocked by the sandbox's permission system as a
  destructive schema action against the live dev database, and not
  routed around — this one mechanism's protection instead rests on a
  live `IntegrityError` demonstration and the passing integration
  test). 1058 tests pass (full suite, up from 1023). Full details in
  `docs/DECISIONS.md`'s FX-44H entry.
- **FX-44H.1: USD effective-date correction (complete)**. A narrow
  factual correction to FX-44H: it correctly separated the FOMC
  decision date from the provider-stored date, but silently assumed
  the stored date always equals the genuine EFFECTIVE date too — wrong
  for the same two rows FX-44H had already flagged (2015-12-16
  "liftoff", 2016-12-14) — the Fed's own Implementation Notes place
  both rows' true effective date one day after the decision date, the
  same gap every other mapped meeting has.
  `USD_EFFECTIVE_TO_DECISION_DATE: dict[date, date]` is replaced by
  `USD_POLICY_TIMINGS: dict[date, UsdPolicyTiming]` — a new domain
  type with `stored_date`/`decision_date`/`effective_date` as three
  genuinely independent, individually-populated fields, never assumed
  equal to one another by a formula. All 30 entries re-expressed as
  full records; the 28 unaffected ones carry forward FX-44H's
  already-verified relationship unchanged, the 2 corrected ones carry
  freshly-fetched Federal Reserve Implementation Note citations.
  `_resolve_usd` now reads `effective_at` from `timing.effective_date`
  (never from `observation_period` directly) via a new `_date_only_
  as_utc_midnight` normalization helper, whose docstring — and a
  matching addition to `MacroObservationVintage.effective_at`'s own —
  is explicit that `00:00 UTC` represents a date-only fact, never a
  claimed verified intraday instant. Remediation went through FX-44H's
  existing `RemediateReleaseTiming`/`correct_verified_release_timing`
  completely unmodified: running it against the corrected registry
  found exactly the 2 affected rows (28 already matched), corrected
  only `effective_at` for each (`released_at` was already right for
  both), and a second run reported both `ALREADY_CORRECT` with zero
  writes — `value`/`revision_sequence`/`series_key`/
  `observation_period` confirmed unchanged directly via SQL and
  dedicated tests. Total row count unchanged at 258; zero duplicate
  rows; zero `CONFLICTING` change points remain across all four
  currencies. Records, but does not solve, a future need for a way to
  REVOKE research-ready status if an EXACT row's timing is later found
  entirely wrong rather than merely imprecise (no declassification
  mechanism exists yet — not needed by either correction in this
  story, both of which stayed EXACT throughout). Regression-proof
  discipline applied to both new checks (the type's ordering
  validation, and `_resolve_usd`'s effective-date sourcing — the
  latter confirmed to break not just the two new domain tests but also
  both remediation-level tests, proving the fix is load-bearing
  through the full pipeline). 1068 tests pass (full suite, up from
  1058). Full details in `docs/DECISIONS.md`'s FX-44H.1 entry.
- **FX-45: pair-relative policy-rate differential (complete)**. A
  deterministic, fully-auditable monetary-policy feature --
  `differential = base_currency_rate - quote_currency_rate`, `Decimal`
  only, never called "carry" -- for EUR/USD, GBP/USD, USD/CAD. New
  `domain.policy_rate_state` (`announced_state_as_of`/`effective_
  state_as_of`/`previous_announced_state`/`previous_effective_state`)
  keeps two rate-state notions structurally separate: ANNOUNCED
  (market-known, gated on `released_at <= T` -- a future-effective-
  but-already-announced rate IS the announced rate, deliberately) and
  EFFECTIVE (operationally in force, gated on a POPULATED `effective_
  at <= T`, never falling back to `released_at`/`observation_period`).
  New `domain.policy_rate_differential` (`RateSemantics`,
  `DifferentialDirection`, `CurrencyRateState`,
  `PolicyRateDifferentialSnapshot`, `PolicyRateDifferentialFeature`,
  `DifferentialUnavailable`, `rate_differential`, `pair_differential_
  change_since_previous`, `classify_direction`) is pure domain logic;
  new `application.use_cases.compute_policy_rate_differential.
  ComputePolicyRateDifferential` orchestrates it against real
  repository history, running every historical read through the
  unmodified FX-44H `require_research_ready_interval` first. Two kinds
  of "no answer" are deliberately not conflated: `ResearchInterval
  NotReadyError` is RAISED for unsafe/insufficient data (JPY's zero
  ingested rows fail this way, via the gate's own `no_baseline` case,
  needing no special-case currency list); `DifferentialUnavailable` is
  RETURNED for a structurally unsupported request (XAU has no
  canonical policy rate; GBP and CAD's EFFECTIVE semantics is
  currently unavailable with present effective-date coverage --
  GBP's exact tier has never had `effective_at` populated by FX-44's
  original resolver,
  CAD is 100% conservative-tier with zero `effective_at` coverage
  either -- confirmed directly via SQL before any code was written,
  and reconfirmed live by both the integration tests and the coverage
  diagnostic below). A new `_AXIS_SAFETY_MARGIN` (14 days) pads every
  readiness-window bound to provably cover the gap between FX-44H's
  `observation_period`-based readiness axis and this story's
  `released_at`/`effective_at`-based state-selection axis (EUR's
  historical six-day gap being the largest offset ever found in this
  registry). `PolicyRateDifferentialFeature` adds three independently-
  computed changes (since the previous policy observation, ~3 months,
  ~6 months), each with a purely mathematically-defined
  `DifferentialDirection` (zero is `UNCHANGED`, no fuzzy band); the
  pair-level "since previous" change uses a "last-mover reversion" --
  only the leg whose current state began more recently is reverted to
  its own previous state. `rate_differential(a, b) == -rate_
  differential(b, a)` proven directly. A new diagnostic, `scripts/
  report_policy_rate_differential_coverage.py`, ran live against real
  Postgres and wrote `research_results/fx45/policy_rate_differential_
  coverage.json`: EUR/USD 49 usable/105 blocked ANNOUNCED (earliest
  ready 2007-03-08), 43 usable/111 blocked EFFECTIVE (earliest ready
  2016-03-10); GBP/USD 78 usable/84 blocked ANNOUNCED (earliest ready
  1998-06-04), 0 usable/162 blocked EFFECTIVE (not ready in this scan);
  USD/CAD 44 usable/79 blocked ANNOUNCED (earliest ready 2015-12-16), 0
  usable/123 blocked EFFECTIVE (not ready in this scan; FX-45H below
  revisits these same numbers with corrected point-in-time semantics
  and a semantics-aware diagnostic axis). A real 2008-01-22
  emergency-cut crisis observation is proven to still correctly block
  an interval that crosses it (integration test, live Postgres). The
  mandatory three-state regression against the real, FX-44H.1-verified
  2026-09-16/17 USD observation (before release / after release but
  before effective / once effective) passes for both semantics, unit
  and integration. Regression-proof discipline applied to three new
  safety-relevant mechanisms (EFFECTIVE's fail-closed `effective_at`
  exclusion, the axis-safety-margin readiness-gate integration, and
  orientation/subtraction order), each deliberately broken, confirmed
  to fail its dedicated tests for the right reason, then restored. No
  SQLAlchemy in the domain layer; no new FastAPI endpoints (none
  required). 1131 tests pass (full suite, up from 1068). Full details
  in `docs/DECISIONS.md`'s FX-45 entry.
- **FX-45H: policy-rate differential point-in-time & coverage
  hardening (complete)**. Three real point-in-time gaps found in FX-45
  itself, fixed without touching accepted FX-45 architecture or
  terminology. (1) `effective_state_as_of` selected the latest
  `effective_at <= T` without also requiring `released_at <= T` --
  wrong: a revision can carry an OLD `effective_at` but a `released_
  at` still in the future. New `domain.policy_rate_state.known_as_of`
  is the shared `released_at <= as_of` filter every function in the
  module now applies first. (2) Even PIT-safe, an OLD decision with a
  populated `effective_at` could still be reported as "the" effective
  state when a NEWER decision was already released with its own
  `effective_at` unestablished -- `effective_state_as_of`/`previous_
  effective_state` now both detect this (ordered by `observation_
  period`, the only axis a vintage without `effective_at` can be
  ordered by) and return `None` instead of silently keeping the old
  rate; `previous_effective_state` gained an explicit `as_of`
  parameter to apply the same PIT filter (its own axis mismatch means
  this is not automatically implied by `current` alone, unlike
  `previous_announced_state`). (3) The readiness window's `end` bound
  previously padded 14 days forward from `as_of` UNCONDITIONALLY,
  letting a genuinely not-yet-released vintage block a historical
  query -- confirmed on a real committed row (USD, 1998-10-15,
  released_at == observation_period == itself, wrongly blocked a
  GBP/USD query at 1998-10-08). `ComputePolicyRateDifferential` now
  narrows history to `known_as_of(history, as_of)` before state
  selection AND the readiness check both run, and the window's
  baseline no longer pads unconditionally. Verified safe for FX-44H's
  carry-in mechanism by direct SQL first: the largest real `released_
  at`-vs-`observation_period` gap, either direction, is under six days
  (EUR) -- far inside the multi-month lookbacks and the margin itself.
  (4) `_AXIS_SAFETY_MARGIN`'s documentation no longer claims 14 days is
  provably sufficient merely because six is the largest gap seen --
  correctness now rests on `known_as_of`'s exact filter, with the
  margin as defensive padding layered on top, not the sole mechanism.
  Terminology: GBP/CAD's EFFECTIVE-semantics unavailability is now
  described as "currently unavailable with present effective-date
  coverage," not "permanently unavailable." Live diagnostic re-run
  (same `research_results/fx45/policy_rate_differential_coverage.json`
  path, now semantics-aware -- ANNOUNCED samples `released_at`
  transitions, EFFECTIVE samples populated `effective_at` transitions,
  each reporting its own `candidate_axis`): GBP/USD ANNOUNCED improved
  78→80 usable (2 previously-wrong blocks lifted, one of them the
  exact real 1998-10-08 case above); EUR/USD EFFECTIVE
  improved 43→44 usable with earliest-ready moving from 2016-03-10 to
  2015-12-17 (FX-44H.1's own "liftoff" effective date) once sampled on
  the correct axis; EUR/USD ANNOUNCED and USD/CAD ANNOUNCED unchanged
  (confirming the fixes are surgical). Regression-proof discipline
  applied to all three mechanisms (4 tests across domain/application/
  integration layers for the PIT filter and the intervening-decision
  block, including a SEPARATE break confirming `previous_effective_
  state`'s own check is independently load-bearing; 2 tests, including
  the real 1998-10-15 integration test, for the readiness-window fix),
  each deliberately broken, confirmed to fail for the right reason,
  then restored. 1145 tests pass (full suite, up from 1131). Full
  details in `docs/DECISIONS.md`'s FX-45H entry.
- **FX-45H.1: policy-rate readiness & revision semantics hardening
  (complete)**. A narrow further hardening pass on FX-45H, correcting
  this codebase's own logic (no new external research). (1) State
  selection and research readiness no longer share one destructively
  filtered view -- a provisional vintage's `released_at` may be an
  uncorroborated proxy (FX-43H), not a verified knowability instant;
  FX-45H's `known_as_of` (now private, renamed `_released_at_on_or_
  before`) is used only by state selection, and `ComputePolicyRate
  Differential` now hands BOTH state selection and `require_research_
  ready_interval` the SAME complete, unfiltered history, matching
  FX-44H's original contract. Verified directly (not assumed) that the
  real 1998-10-15 worked example stays correctly excluded from the
  readiness window -- via its `observation_period` falling outside the
  computed bound, never via trusting its own `released_at`. (2)
  `announced_state_as_of` now selects by observation identity: among
  vintages knowable at `T`, the latest `observation_period` present,
  then that observation's own latest admissible revision -- a
  correction republished later for an OLDER observation no longer
  wrongly resurrects it as current. `previous_announced_state` gained
  an explicit `as_of` parameter for the identical reason. (3) A
  same-observation higher revision with unresolved `effective_at` now
  also blocks EFFECTIVE (previously only a later, different
  observation_period did) -- `revision_sequence` is reserved for
  genuine value corrections to the SAME decision, so an unresolved
  higher-revision sibling supersedes an older sibling's own effective
  timing. Diagnostic regenerated: every headline usable/blocked number
  is UNCHANGED from FX-45H (verified via a full before/after diff
  showing zero verdict flips, not assumed) -- GBP/USD ANNOUNCED's
  78→80 improvement holds for the same legitimate, window-bound reason
  the real 1998 case does. A real, previously-uncaught instance of the
  actual bug DID surface: several already-blocked entries (USD
  `2020-03-04`, GBP `1997-06-02`) now correctly list an additional
  offending observation FX-45H's design had silently pruned -- verdict
  unchanged (already blocked for another reason), reason now complete.
  Regression-proof discipline applied to all three new mechanisms,
  including proving a new synthetic test catches a reversion the real
  1998 data cannot (it's excluded by the window bound regardless).
  1150 tests pass (full suite, up from 1145; 2 unrelated live-OANDA
  transient failures confirmed via re-run, not a regression). Full
  details in `docs/DECISIONS.md`'s FX-45H.1 entry.
- **FX-46: historical policy-rate differential research (complete)**.
  The first real research EXPERIMENT against the hardened feature --
  not a trading strategy. Two pre-registered hypotheses (LEVEL: sign
  of the differential vs. subsequent return, one ISO-week sample;
  CHANGE: INCREASED vs. DECREASED vs. subsequent return, every D-bar,
  no change inferred across a blocked/unavailable gap), run separately
  per pair (EUR/USD, GBP/USD, USD/CAD) and semantics (ANNOUNCED/
  EFFECTIVE), never pooled or cross-falling-back. New `src/forex_agent/
  research/policy_rate_differential_research.py` (pure functions,
  one async seam -- `evaluate_feature`, the only place FX-46 touches
  `ComputePolicyRateDifferential`) plus `scripts/run_fx46_policy_rate_
  differential_research.py` (real orchestration: DB reads, ~41,000
  feature evaluations across all pairs/semantics/experiments via a
  read-through cache over the 4 distinct currencies' history, per-cell
  statistics, primary-contrast bootstrap, artifact writers). No native
  `D`-granularity candles existed anywhere -- `scripts/aggregate_d_
  candles.py` (new) materializes them via the EXISTING `AggregateCandles`
  use case (FX-7) from native `H4`; real coverage is 2005-01-02 onward
  for all three pairs. `domain/block_bootstrap.py` (FX-39) gained
  `calendar_year_cluster_bootstrap_differences`, reusing FX-39's own
  `NUM_RESAMPLES = 10_000` convention (seed=46). Real results: GBP/USD
  and USD/CAD EFFECTIVE are entirely unavailable (0 usable, confirming
  FX-45H's coverage diagnostic at full scale); EUR/USD EFFECTIVE has
  real usable coverage (427 LEVEL weeks, all `NEGATIVE` -- EUR's
  effective rate never exceeded USD's in the covered window); the
  large majority of ANNOUNCED contrasts have a 95% CI including zero
  (cannot distinguish from noise); one adverse result (USD/CAD
  ANNOUNCED/CHANGE, 20d: CI excludes zero in the direction OPPOSITE the
  pre-registered hypothesis, small n) reported honestly, not
  reinterpreted. A real bug (summary aggregation grouping by a raw,
  per-row-unique `DifferentialUnavailable` reason string, inflating
  the first-run JSON/markdown to several MB) was found after seeing
  results, fixed (summary-reporting code only, CSV detail untouched),
  and ALL artifacts regenerated from a clean run. Regression-proof
  discipline applied to all 5 named mechanisms (next-bar entry,
  return orientation, gap suppression, change classification, cluster-
  bootstrap grouping), each genuinely broken, confirmed to fail,
  restored. 32 new tests; 1182 pass (full suite, up from 1150). Full
  details, complete results table, and limitations in `docs/
  DECISIONS.md`'s FX-46 entry and `research_results/fx46/
  policy_rate_differential_summary.md`. **Superseded in part by
  FX-46H below** -- the EUR/USD ANNOUNCED/LEVEL contrast reported here
  as a CI including zero was actually computed from a bootstrap bug;
  see FX-46H for the corrected result.
- **FX-46H: bootstrap validity & research artifact reproducibility
  (complete)**. An external review of FX-46 found `calendar_year_
  cluster_bootstrap_differences` (`domain/block_bootstrap.py`)
  fabricated a zero mean for whichever arm of a two-group contrast was
  empty in a given bootstrap replication -- real for EUR/USD ANNOUNCED/
  LEVEL, whose `POSITIVE` group is 8 observations all in one calendar
  year (2008): 3,603 of 10,000 replications at seed=46 omitted 2008
  and were scored against a fabricated `POSITIVE` mean of 0, directly
  producing the reported (distorted) CI. Fixed: the function now
  returns a `ClusterBootstrapOutcome` and either REDRAWS a
  replication's year sample (bounded by `max_redraw_attempts`) when a
  draw would leave an arm empty, or reports the whole contrast
  `NOT_ESTIMABLE` -- never fabricating a value -- when an arm has
  fewer than 2 distinct calendar-year clusters to begin with, or when
  the redraw cap is exhausted. Separately, the committed FX-46
  artifacts recorded a stale `git_commit` (the script reads `git
  rev-parse HEAD` at run time; FX-46 ran against its own uncommitted
  working tree) and a `candle_end_bound` that was a query bound, not
  the actual data cutoff -- the script now also records
  `git_commit_dirty`/`git_dirty_paths` (scoped to `src/forex_agent`
  and itself, not repo-wide, which would read dirty forever due to
  `.claude/` staying untracked by convention),
  `candle_end_actual_by_instrument` (the real max D-candle timestamp
  used per pair), and `macro_data_fingerprint` (a deterministic hash
  of the exact policy-rate vintage history read). Regression-proof
  discipline applied (reverted to the fabricated-zero-mean formula,
  confirmed 2 new tests fail for the right reason, restored). Full
  FX-46 experiment re-run from the clean, corrected commit against the
  same real data: 41,008 sample rows, identical to the original run;
  exactly 3 cells changed (EUR/USD ANNOUNCED/LEVEL, all 3 horizons) --
  point estimates unchanged, CIs now `NOT_ESTIMABLE`; no other contrast
  in the report changed. FX-46's "every ANNOUNCED CI includes zero"
  claim is corrected: that contrast has no CI at all, not a CI that
  happens to include zero. 3 new tests, 1 rewritten; 1185 pass (full
  suite, up from 1182). Full details in `docs/DECISIONS.md`'s FX-46H
  entry and the regenerated `research_results/fx46/
  policy_rate_differential_summary.md`.
- **FX-47: rate differential x existing technical/regime evidence
  (complete)**. ATTRIBUTION, not gating, of the policy-rate differential
  (FX-42-FX-46H) against trades TWO EXISTING, already-committed
  strategies -- `MultiTimeframeTrendStrategy` (the "H1/H4 trend trade"
  pattern) and `CloseChannelBreakoutStrategy` -- generate
  UNCONDITIONALLY on EUR/USD, GBP/USD, USD/CAD (the three pairs with
  real differential coverage; USD/JPY, these candidates' original
  FX-38/39 holdout pair, has zero ingested policy-rate data, FX-42H.1's
  provider mapping left unresolved). Exactly FX-21/FX-21H's own
  `segment_trades_by_regime` shape: no strategy parameter changed, no
  trade gated/suppressed, every trade bucketed after the fact by two
  independent axes -- LEVEL (does the differential's sign at entry
  SUPPORT/OPPOSE/sit NEUTRAL relative to the trade's direction, one
  fresh `evaluate_feature` call per trade at its exact `entry_time`) and
  CHANGE (FX-46's own per-D-bar INCREASED/DECREASED/UNCHANGED
  classification for whichever D-bar governs the trade's entry, reused
  unmodified). New `research/rate_differential_attribution.py` (pure)
  + `scripts/run_fx47_rate_differential_attribution.py` (real
  orchestration over ~138,000 native H1 candles/pair). New
  `IncrementalCloseChannelBreakoutStrategy` (O(n) sibling to the
  existing O(n^2) strategy, parity-tested), needed for this story's
  own full-history backtest scale -- the same performance fix FX-29
  already applied to every other strategy in this suite. **Real
  result**: level/change bucket totals match each strategy's own trade
  count exactly in every one of the 12 (strategy, instrument,
  semantics) cells -- no trade silently dropped. Across roughly 150
  bucket-level 95% CIs computed, the large majority include zero (no
  reliable interaction established), consistent with a handful
  excluding zero by chance alone at that rate -- no multiple-comparison
  correction was applied (unlike FX-39's own small, pre-registered
  candidate set), so this is reported as a caveat, not suppressed. The
  one substantial-n exception: EUR/USD `CloseChannelBreakoutStrategy`
  ANNOUNCED/LEVEL's `SUPPORTS` bucket (n=957) has a 95% CI entirely
  below zero -- trades where the differential's sign matched the
  trade's own direction performed WORSE than trades where it didn't,
  opposite the naive "carry supports direction" intuition -- reported
  factually, not treated as a signal to act on. Regression-proof
  discipline applied to both new safety-relevant mechanisms (the
  SUPPORTS/OPPOSES sign mapping, the look-ahead-safe D-bar join) plus
  the incremental strategy's own window ordering. 25 new tests, 1210
  pass (full suite, up from 1185). Full results: `research_results/
  fx47/`. Full details in `docs/DECISIONS.md`'s FX-47 entry. **Superseded
  by FX-47H below** -- the EUR/USD "exception" above did not survive a
  proper joint contrast; the multiplicity count ("roughly 150") was
  also wrong (actual: 89).
- **FX-47H: attribution validity & provenance hardening (complete)**.
  An external review of FX-47 found its per-bucket bootstraps each
  tested only "is this bucket's own mean distinguishable from zero?",
  never "do SUPPORTS and OPPOSES (or INCREASED and DECREASED) actually
  differ?" -- the reported EUR/USD exception didn't survive a proper
  joint contrast: `mean(SUPPORTS) - mean(OPPOSES) = -0.0004732`, 95% CI
  (FX-46H's own joint calendar-year cluster bootstrap, 13 clusters each
  side) `[-0.00119, +0.00009]` -- crossing zero. Fixed: each cell now
  computes a joint calendar-year cluster bootstrap contrast (reusing
  `calendar_year_cluster_bootstrap_differences` unchanged) as the
  PRIMARY inferential result; per-bucket stats remain, relabeled
  descriptive-only. Also restored the FX-46H-style provenance FX-47 had
  regressed on (actual max H1/H4/D timestamp per instrument,
  macro-vintage fingerprint/count/max `released_at`), corrected the
  multiplicity count (89 descriptive bucket CIs, 13 excluding zero --
  not "roughly 150"), and fixed `IncrementalCloseChannelBreakoutStrategy`'s
  own complexity description (O(`lookback`) per bar, not O(1)). **Real,
  corrected result**: of the now 15 estimable primary contrasts (8
  LEVEL + 7 CHANGE; the rest `NOT_ESTIMABLE` or not computable for zero
  observations), exactly ONE excludes zero -- GBP/USD
  `MultiTimeframeTrendStrategy` ANNOUNCED/LEVEL, SUPPORTS (n=238) vs.
  OPPOSES (n=237), 95% CI `[-0.00323, -0.00040]` -- roughly consistent
  with the ~5% base rate expected across this many tests, reported
  factually and not treated as a signal to act on. The original EUR/USD
  `CloseChannelBreakoutStrategy` "exception" is gone under the correct
  methodology. No new strategy, pairs, buckets, thresholds, or gating.
  Full details in `docs/DECISIONS.md`'s FX-47H entry.
- **FX-48: tradable carry / financing feasibility (complete)**. A
  feasibility investigation, not an assumed build -- also folded in a
  minor FX-47 cleanup (its markdown said "see `git_dirty_paths`" but
  the report never stored that field; fixed and `research_results/
  fx47/` regenerated, all computed statistics unchanged). This
  project's first ADR: `docs/adr/0001-tradable-carry-financing-data-
  sourcing.md`. Three candidates investigated, nothing fabricated from
  today's broker table: **market-quoted FX forward/swap points** -- NOT
  VIABLE, no free/legal historical source meeting this project's
  requirements was found (a commercial Bloomberg/Refinitiv/ICE-class
  product in practice), and OANDA doesn't even quote FX forwards
  (spot/CFD only, confirmed). **OANDA's own historical financing/
  rollover** -- NOT VIABLE for backtesting, verified live against the
  real practice API: `/v3/accounts/{id}/instruments` exposes only a
  CURRENT snapshot (checked: EUR/USD longRate=-0.0247/shortRate=+0.0045,
  genuinely asymmetric; triple-roll day is Wednesday for EUR/USD but
  Thursday for USD/CAD -- a concrete instrument-specific exception to
  the usual convention, consistent with USD/CAD's own T+1 settlement);
  `/v3/accounts/{id}/transactions` (`DAILY_FINANCING`) returned ZERO
  records for this project's own practice account (created
  2026-09-13, never held a real position) -- no historical time-series
  endpoint exists independent of an account's own transaction history.
  **Overnight benchmark rate differential** (SOFR/€STR/SONIA/CORRA) --
  VIABLE: all four map onto the SAME FOUR PROVIDERS this project
  already uses for policy rates (FRED/ECB/BoE/BoC), confirmed directly,
  with full instrument coverage actually BETTER than the existing
  policy-rate differential (no GBP/CAD EFFECTIVE-gap, since a daily
  rate has no ANNOUNCED/EFFECTIVE split). Real methodology breaks on
  BOTH the GBP leg (SONIA reformed 2018-04-23) and the CAD leg (CORRA
  reformed 2020-06-15, Bank of Canada took over from Refinitiv) --
  neither a homogeneous single-methodology series across its full
  history. Also: SOFR/CORRA are SECURED repo benchmarks while €STR/
  SONIA are UNSECURED wholesale benchmarks -- a real economic
  heterogeneity across the three pairs' own contrasts, not just a
  naming nicety, which is why this candidate is named "overnight
  benchmark rate differential" rather than "funding-rate differential."
  **Decision**: don't pursue A or C; B's minimal ingestion design is
  PROPOSED in the ADR (reusing `MacroSeriesDefinition`/
  `MacroObservationVintage`/`ProviderSeriesMapping` unchanged) but NOT
  implemented -- pending separate sign-off. Even if built, B would
  still not be literal tradable carry (no cross-currency basis, no
  broker markup) and must never be labeled "carry." Full details in
  `docs/DECISIONS.md`'s FX-48 entry. **Stop after FX-48 -- no ingestion
  code for the benchmark-rate differential without an explicit new
  story.**
- **FX-49: rate-expectations data-source feasibility (DEFER)**. A pure
  source-feasibility investigation -- explicitly not an expected-rate-
  differential build -- into whether the project can obtain a
  defensible, point-in-time-safe historical record of what the MARKET
  EXPECTED future policy rates to be (3/6/12-month forward), as
  opposed to the current/observed rates FX-42-FX-48 already cover.
  This project's second ADR: `docs/adr/0002-rate-expectations-data-
  source-feasibility.md`. Three parallel primary-source research
  passes (USD; GBP+EUR; CAD) found: a real, liquid futures instrument
  exists for every currency (Fed Funds futures/SOFR futures for USD,
  SONIA futures for GBP, Euribor/€STR futures for EUR, CORRA futures
  for CAD) -- though not all are long-established (CAD's cleanest
  instrument dates only to 2020, EUR's most comparable one only to
  2023) -- and a futures settlement price is genuinely
  point-in-time-safe (a contemporaneous exchange-determined settlement
  value, not one reconstructed after the fact) -- but the multi-year
  historical backfill this project would need is gated behind a paid
  commercial subscription for every currency (current/same-day
  publication is free on several of these exchanges' own sites;
  multi-year depth is not) -- CME DataMine/ICE Data Services/TMX
  Datalinx -- each with redistribution-restricted licensing. A critical
  PIT trap was found and avoided: CME's derived "Term SOFR" benchmark
  really launched 2021-04-21 for its 1M/3M/6M tenors and 2021-09-21 for
  its 12-month tenor (2022-05-19 was the ARRC's later, separate formal
  endorsement of the already-live 12-month tenor, not its first
  publication), so any "historical" value dated before its own tenor's
  real launch would be a back-calculated reconstruction, not a genuine
  observation -- the raw SOFR futures prices themselves (from
  2018-05-07) don't have this problem. A second complication: EUR's two
  real candidates trade off depth (Euribor futures, ~28y, but a
  credit/liquidity-premium-bearing term rate) against comparability
  (€STR futures, which improve on Euribor by pricing an overnight
  risk-free rate but still don't fully match SOFR/CORRA's secured-repo
  character, and are <3 years old) -- no currently-available EUR
  instrument is both deep and free of every comparability gap.
  **Decision: DEFER**, not NO-GO, not GO --
  reopening requires an explicit commercial-licensing decision this
  story has no authority to make, plus the EUR instrument choice, plus
  several UNRESOLVED technical items. No FX-50 implementation contract
  written (only required on GO, per the story's own instruction). Full
  details in `docs/DECISIONS.md`'s FX-49 entry. **Stop after FX-49 --
  FX-50 remains gated on FX-49's own reopening conditions; no
  commercial data subscription was added or authorized.**
- **FX-51: point-in-time economic event model (complete)**. First
  story of a new epic, `FX-EPIC-07 Economic Event Risk` -- a
  provider-neutral, point-in-time-safe domain and persistence model
  for scheduled economic events and their released values, explicitly
  NOT a calendar-ingestion story: no provider chosen or integrated, no
  real data populated. New domain types
  (`domain/economic_event_occurrence.py`/`economic_event_schedule_
  vintage.py`/`economic_event_consensus_vintage.py`/`economic_event_
  actual_value_vintage.py`/`economic_indicator_definition.py`/
  `economic_event_state.py`/`economic_event_status.py`/
  `availability_confidence.py`): an occurrence's identity is
  `(indicator_key, reference_period)`, never a scheduled timestamp; a
  reschedule/consensus revision/actual-value revision is always a NEW
  immutable vintage row (a later `availability`, a higher `revision_
  sequence`) -- the same one-row-per-revision shape `MacroObservation
  Vintage` (FX-41) already established, with no UPDATE path anywhere
  in this story. `EconomicEventActualValueVintage` deliberately has no
  `previous_value`/`surprise` field (both are PIT traps; both must be
  derived later, FX-53, from this same vintage history). `availability`
  is `None` iff `availability_confidence` is `UNKNOWN` (enforced in
  `__post_init__` and by a database `CHECK` constraint) -- a backfilled
  fact with genuinely unknown historical availability can never become
  visible at any `as_of`, however far in the future. Persistence: 4
  new tables via Alembic migration `bb7551fcef3a`
  (`economic_event_occurrences` + 3 vintage tables), each vintage table
  referencing its occurrence through a composite `FOREIGN KEY` on the
  natural key `(indicator_key, reference_period)` (mirrors
  `MacroObservationVintage`'s own natural-key-reference pattern, not a
  surrogate-UUID FK). `application/ports/economic_event_repository.py`
  / `infrastructure/db/economic_event_repository.py` implement the
  Section-14 PIT query contract (`schedule_as_of`/`consensus_as_of`/
  `actual_value_as_of`/`first_release_as_of`/`known_events_in_window`);
  `application/use_cases/get_economic_event_state.py` assembles all
  four for one occurrence at one instant. 43 domain unit tests + 20
  live-Postgres integration tests, all passing; full details in
  `docs/DECISIONS.md`'s FX-51 entry. No new ADR -- an implementation of
  an already-approved conceptual model, not a fresh architectural
  trade-off. **Stop after FX-51 -- FX-52 (economic calendar + surprise
  ingestion) has NOT been started; no calendar provider chosen; no
  real event data populated; no surprise calculation implemented; no
  trading rule or risk weight added for any event.** **Superseded in
  part by FX-51H** (below): occurrence identity is no longer
  `(indicator_key, reference_period)` -- see FX-51H's own bullet for
  the corrected model; everything else in this bullet (vintage shape,
  fail-closed availability, no persisted previous/surprise) remains
  accurate.
- **FX-51H: point-in-time economic event model hardening (complete)**.
  Hardens FX-51's model in place, before FX-52 began. (1) **Occurrence
  identity decoupled from reference period**:
  `EconomicEventOccurrence.occurrence_key` (a stable, caller-assigned
  string) replaces `(indicator_key, reference_period)` as identity;
  `reference_period` is now `UtcTimestamp | None` -- a qualitative/
  irregular event (an FOMC press conference, meeting minutes) can exist
  with no reference period at all, rather than one being fabricated.
  Every vintage table's own `FOREIGN KEY`/unique constraint is re-keyed
  onto `occurrence_key` alone. (2) **New fact type**:
  `domain/economic_event_release_vintage.py`
  (`EconomicEventReleaseVintage`) records the provider-neutral "this
  occurrence actually occurred/was released on `released_date`[/
  `released_time`]" fact, independent of whether a numeric value
  exists -- fixing FX-51's own gap where a qualitative event had no
  honest way to record its own occurrence at all. Same immutable
  one-row-per-revision shape as every other FX-51 vintage; own
  `released_time: time | None` never-fabricate-an-unknown-time contract
  mirroring `scheduled_time`'s. (3) **`known_events_in_window` now
  resolves true timezone instants**: `domain/economic_event_state.py::
  schedule_within_window` (pure, independently unit-tested) replaces
  FX-51's own local-date-vs-UTC-date comparison with an exact UTC
  instant test for a known-time schedule, and a full local-day UTC
  instant-range overlap test for a date-only/TBD one (never a
  fabricated single instant). (4) **`release_group_key` may be attached
  after occurrence creation**: `attach_release_group`, a second
  narrowly-scoped legitimate mutation (an atomic conditional `UPDATE
  ... WHERE release_group_key IS NULL`, idempotent for a repeat,
  `ValueError` for a genuine conflict) -- mirrors FX-43H's own
  `replace_provisional_release_timing` precedent; legitimate because
  grouping was never a vintaged, temporal fact. (5) The repository/use-
  case PIT contract gained a `release`/`release_as_of` axis, and every
  occurrence-identifying parameter changed to `occurrence_key` alone.
  Migration `76a4b23b2129` performs the re-keying with columns added
  directly as `NOT NULL` (no backfill step) because all affected tables
  were verified EMPTY immediately before the migration was written --
  documented as a one-off, not a general pattern. Verified up/down/up
  against live Postgres. 67 domain unit tests + 32 live-Postgres
  integration tests, all passing; full details in `docs/DECISIONS.md`'s
  FX-51H entry. No new ADR. **Stop after FX-51H -- FX-52 still has NOT
  been started; no calendar provider chosen; no real event data
  populated.**
- **FX-51H.1: economic event model final integrity patch (complete)**.
  Two small gaps closed, no redesign. (1) `attach_release_group` now
  rejects a non-string/empty/whitespace-only `release_group_key` with
  `ValueError` BEFORE any SQL runs (the identical validation
  `EconomicEventOccurrence.__post_init__` already applies at
  construction time, which this method's own argument never passed
  through). (2) Migration `76a4b23b2129`'s downgrade -- previously only
  documented as unsafe against real data -- now enforces that at
  runtime: `_raise_if_downgrade_would_lose_data` checks all five tables
  it touches and raises `RuntimeError` naming the offending table
  before any DDL runs, a PERMANENT limitation (no old-schema
  equivalent for `economic_event_release_vintages`; a `NULL`
  `reference_period` and duplicate `(indicator_key, reference_period)`
  pairs are both unrepresentable under the old schema's own
  constraints), verified directly against live Postgres plus a new
  mock-`op` unit test module mirroring this project's existing
  migration-testing precedent. 14 new tests (6 integration + 8 unit);
  1338 tests pass overall. Full details in `docs/DECISIONS.md`'s
  FX-51H.1 entry. No new ADR. **Stop after FX-51H.1 -- FX-52 still has
  NOT been started.**
- `find_gaps` (`forex_agent.domain.candle_gaps`, day-alignment fixed
  FX-26) + `DetectDataGaps` use case: reports missing expected candle
  timestamps in a stored range, now using `candle_boundary` (the same
  latent day-alignment bug FX-24 already fixed elsewhere — verified and
  regression-tested). Rejects candles spanning more than one instrument
  (FX-11H — a candle from a different instrument could previously mask a
  real gap). `DetectDataGaps` snaps `start` to its own candle boundary
  before fetching or checking for gaps (FX-27H.1) — a non-boundary-
  aligned `start` previously made `get_range`'s `>= start` filter and
  `find_gaps`' own boundary-rounding disagree, falsely reporting a
  genuinely-present boundary candle as missing. No market-calendar
  awareness (weekends/holidays) — callers pass ranges already known to
  be within a trading session (see the research dataset gap-check,
  above, for the caller-side weekly-closure filtering this implies in
  practice).
- `TradeHypothesis`, `Strategy` Protocol, `run_strategy`
  (`forex_agent.domain.strategy`) — the strategy framework. No I/O; lives
  in `domain/` alongside `aggregate_candles`/`find_gaps`. `run_strategy`
  structurally enforces "strategies must only evaluate finalized candles"
  before delegating to a strategy, rather than trusting each
  implementation to check it. `TradeHypothesis` carries full provenance
  (FX-13): `timeframe`, `strategy_key`, `strategy_version`, `parameters`
  (a hashable tuple of string pairs, not a `dict` — `params_from_dict`
  builds it from a strategy's typed params), all required on every
  hypothesis. Its directional field is `target_position: TargetPosition`
  (`forex_agent.domain.target_position`, FX-18) — LONG/SHORT/FLAT,
  distinct from the execution-only `TradeSide` (LONG/SHORT) used by
  `Price`/`SimulatedTrade`: a strategy can ask to be flat, which
  `TradeSide` cannot express.
- `EmaCrossoverStrategy` (`forex_agent.domain.strategies.ema_crossover`,
  `strategy_key="ema_crossover_v1"`) — the first concrete `Strategy`
  (FX-14), and the reference strategy the roadmap in `docs/DECISIONS.md`
  is built around. 20/50 SMA-seeded EMA crossover on synthetic-midpoint
  close, deliberately minimal (no ADX/RSI/confirmation/optimization).
  Fires only on the bar the crossover actually happens, not every bar one
  EMA stays above the other. Verified: against an independent reference
  EMA calculation (same rigor as ADX), through `run_backtest` +
  `simulate_trades` on an engineered synthetic series with hand-verified
  execution prices, and against live OANDA practice candles.
- `CloseChannelBreakoutStrategy` (`forex_agent.domain.strategies.
  close_channel_breakout`, `strategy_key="close_channel_breakout_v1"`) —
  the second concrete `Strategy` (FX-15). LONG when the current close
  exceeds the highest close of the `lookback` bars strictly before it,
  SHORT when below the lowest — close-based, not high/low (FX-12H's
  synthetic-midpoint-extrema caveat applies to highs/lows, not closes).
  Fires every qualifying bar, not just the first breakout — FX-11's
  same-direction no-op absorbs repeats safely, so no edge-detection logic
  was needed. Verified the same way as EMA: through `run_backtest` +
  `simulate_trades` on an engineered series with hand-traced prices
  (including an edge case where entry and end-of-data force-close land on
  the same final candle), and against live OANDA practice candles. Run
  across the full 10-year, 5-instrument research dataset (FX-34),
  default `lookback=20`: genuinely mixed — unprofitable on `EUR_USD`/
  `GBP_USD`/`USD_CAD`, profitable on `USD_JPY`/`XAU_USD`, no obvious
  pattern separating them — see `docs/DECISIONS.md`.
- `TimeSeriesMomentumStrategy` (`forex_agent.domain.strategies.
  time_series_momentum`, `strategy_key="time_series_momentum_v1"`) — the
  third concrete `Strategy` (FX-16). `return = current_close /
  close_N_bars_ago - 1` against a single symmetric `threshold` (default
  `Decimal("0")`, the pure baseline — a deadband is just `threshold > 0`,
  no constructor shape change needed). Fires every qualifying bar, same
  precedent as the close-channel breakout. Verified through
  `run_backtest` + `simulate_trades` on an engineered series that
  *naturally* (not specifically contrived for it) exercised FX-11H's
  final-bar-not-actionable rule — the series' last hypothesis lands on
  the final candle and is correctly dropped — and against live OANDA
  practice candles. Run across the full 10-year, 5-instrument research
  dataset (FX-33), default params: unprofitable on 4 of 5 instruments
  (profit factor 0.73-0.97) at n=6,000+ trades each; `XAU_USD` the one
  exception, marginally profitable — see `docs/DECISIONS.md`.
- `MeanReversionStrategy` (`forex_agent.domain.strategies.
  mean_reversion`, `strategy_key="mean_reversion_v1"`) — the fourth
  concrete `Strategy` (FX-19), and the first to actually emit
  `TargetPosition.FLAT` (FX-18) rather than just carrying the renamed
  field. Bollinger-Bands-style z-score: LONG when the current close is
  `entry_threshold` population standard deviations below its own
  `period`-bar rolling mean (oversold), SHORT when that far above
  (overbought), FLAT when the z-score crosses back through zero — a real
  zero-crossing test (same technique as FX-14's EMA crossover), not a
  magnitude deadband, so it implements "exit z=0.0" literally. The
  rolling window includes the current bar (standard Bollinger
  definition, at the cost of a known self-referential-dampening
  trade-off — documented, not treated as a defect); stddev is
  population, not sample. `entry_threshold` must be strictly positive
  (FX-21H.1) — at `0` the FLAT zero-crossing branch would be
  unreachable. Verified against an independently hand-derived
  synthetic series with exact clean z-scores at every relevant bar,
  through `run_backtest` + `simulate_trades` (confirming FLAT-closes-
  without-reopening produces the right trade count end to end), and
  against live OANDA practice candles. Run across the full 10-year,
  5-instrument research dataset (FX-35), default params: unprofitable
  on **every single instrument** (profit factor 0.74-0.98) despite a
  consistently HIGH win rate (0.60-0.63) throughout — many small wins,
  fewer larger losses, the classic mean-reversion failure signature —
  see `docs/DECISIONS.md`.
- `VolatilityExpansionBreakoutStrategy` (`forex_agent.domain.strategies.
  volatility_expansion`, `strategy_key="volatility_expansion_breakout_v1"`)
  — the fifth concrete `Strategy` (FX-20). LONG/SHORT when the current
  close breaks a Donchian high/low channel (built from actual highs/
  lows, unlike FX-15's close-based channel — a deliberate reversal,
  since ATR already requires and accepts the midpoint-averaged highs/
  lows anyway) *and* the short-period/long-period ATR ratio is at least
  `expansion_threshold` — a breakout with no expansion, or an expansion
  with no fresh breakout, opens nothing. FLAT when the expansion ends
  (ratio crosses back below `expansion_threshold`, reused directly as
  the exit boundary — no separate deadband parameter, same reasoning as
  FX-19). True Range/Wilder ATR smoothing duplicated locally from
  `regime_detection.py`'s own ADX logic (deliberate, documented, not
  shared via a helper — see `docs/DECISIONS.md`). Verified against an
  independently hand-derived synthetic series covering all five
  `evaluate()` outcomes, through `run_backtest` + `simulate_trades`
  (confirming FLAT-closes-without-reopening end to end), and against
  live OANDA practice candles. `IncrementalWilderAtr` (`forex_agent.
  domain.incremental_atr`) + `IncrementalVolatilityExpansionBreakout
  Strategy` (FX-36) — O(1)-per-bar counterparts, golden-parity-tested
  including a hand-constructed exact-threshold boundary case; this
  strategy remains completely unmodified as the reference. Run across
  the full 10-year, 5-instrument research dataset: only n=11-27 trades
  per instrument (the double breakout-AND-expansion condition is rare
  at default params) — too small a sample for a confident finding
  either way, unlike FX-32/34/35's runs — see `docs/DECISIONS.md`.
- `MultiTimeframeTrendStrategy` (`forex_agent.domain.strategies.
  multi_timeframe_trend`, `strategy_key="multi_timeframe_trend_v1"`,
  FX-25, H4 visibility canonicalized FX-25H) — the sixth concrete
  `Strategy`, and the first needing two candle series at once. H1
  EMA-crossover entry, gated by H4's own EMA fast/slow *state* (not a
  crossover event): confirmed → `LONG`/`SHORT`; H1 fires but H4
  disagrees (or has insufficient history, or is neutral) → `FLAT`,
  resolving FX-21H's own flagged reversal-vs-FLAT question.
  `Strategy.evaluate(candles: list[Candle])`'s signature is unchanged —
  the full H4 series is a constructor argument, filtered on every call
  to only bars fully closed strictly before the current H1 bar, using
  `candle_boundary.candle_end_time` (FX-25H — the original version used
  a fixed "4 elapsed hours" assumption that disagreed with FX-24's own
  DST-aware logic and was wrong on a fall-back day; proven no-look-ahead
  via a mutation regression, same technique as FX-21H's). Also rejects a
  driving series that isn't `Granularity.H1` (FX-25H). Verified through
  a hand-derived synchronized H1+H4 series covering all four outcomes,
  through `run_backtest` + `simulate_trades`, and against live OANDA
  candles at both granularities. This closes out the original
  strategy-suite roadmap — see `docs/DECISIONS.md`'s FX-25/FX-25H
  entries. `IncrementalMultiTimeframeTrendStrategy` (FX-37) — the sixth
  and final `IncrementalStrategy` counterpart, and the only one needing
  two candle series: `IncrementalStrategy.on_candle` only ever receives
  one stream, so the full H4 series stays a constructor argument (same
  shape as the slow strategy) while an internal cursor advances into it
  as H1 time progresses, feeding each newly-visible H4 candle into a
  reused `IncrementalSmaSeededEma` pair exactly once, in order, instead
  of refiltering and recomputing the H4 EMA from scratch every H1 bar.
  Golden-parity-tested against the unmodified slow strategy, including
  the FX-25H DST fall-back regression reused verbatim and a
  hand-constructed edge case closing a real gap: the slow strategy's
  own H4-bias gate requires `slow_period + 1` *visible* candles, one
  more than `_sma_seeded_ema` itself needs to produce a value, so an
  incremental EMA tracker's own readiness would fire one candle too
  early without an explicit extra counter (confirmed via regression-
  proof discipline — removing the counter makes the new test fail,
  restoring it passes again). Run across the full 10-year, 5-instrument
  research dataset: n=425-462 trades per instrument, genuinely mixed —
  unprofitable on `EUR_USD`/`GBP_USD`/`USD_CAD` (profit factor
  0.90-0.92), profitable on `USD_JPY`/`XAU_USD` (profit factor
  1.25-1.31) — with a consistently LOW win rate (0.28-0.34) throughout,
  the classic trend/breakout-confirmation signature (few larger wins,
  many small losses), the opposite of FX-35's mean-reversion one. Full
  table in `docs/DECISIONS.md`. This closes out the user-authorized
  batch of running every remaining concrete strategy across the
  research dataset (FX-32 through FX-37).
- `RegimeSegmentedTrades` + `segment_trades_by_regime`
  (`forex_agent.domain.regime_segmentation`, FX-21, look-ahead fixed
  FX-21H): performs **entry-regime attribution** — buckets a strategy's
  already-executed `SimulatedTrade`s by the `TrendRegime` (FX-12) in
  effect strictly *before* each trade's `entry_time` (the entry candle
  itself is excluded: only its open, not its high/low/close, is known
  at the instant of entry) — `.trending`/`.ranging`/`.unclassified`
  (the last for trades too early to have `2 * period` candles of prior
  history, the normal case, not an error). This is attribution, not
  regime-*gating*: EMA runs unconditionally and takes every signal it
  normally would; regime only labels completed trades afterward — see
  `EmaCrossoverTrendRegimeGatedStrategy` (FX-28, below) for the actual
  gating counterpart. Connects
  `classify_regime` and `compute_metrics` for the first time;
  `compute_metrics` needed no changes, exactly the composable
  segmentation FX-17 was designed for. No strategy was modified —
  regime stays structurally external. First used by
  `tests/replay/test_ema_regime_conditioned.py` (a live-OANDA test
  asserting only structural properties, never a specific winner) to
  produce a real empirical finding, recorded in `docs/DECISIONS.md`.
  Second use (FX-23): `MeanReversionStrategy` vs. `RANGING`, same
  attribution framing, same ~90-day EUR/USD H1 window. Both experiments
  so far found the "obvious" regime pairing underperforming the "wrong"
  one — see `docs/DECISIONS.md` for both tables.
- `EmaCrossoverTrendRegimeGatedStrategy` (`forex_agent.domain.strategies.
  ema_crossover_trend_regime_gated`, `strategy_key=
  "ema_crossover_trend_regime_gated_v1"`, FX-28) — the true
  `TrendRegime`-*gating* counterpart to attribution, above: the same EMA
  crossover event as `EmaCrossoverStrategy`, but a crossover only
  confirms (`LONG`/`SHORT`) if `classify_regime` says
  `TrendRegime.TRENDING`; `RANGING` or insufficient regime history closes
  to `FLAT` instead — same FLAT-vs-None precedent as
  `MultiTimeframeTrendStrategy`. **Proven** (not just observed): for this
  specific pairing, gated trades are entry/exit/P&L-*identical* to
  `segment_trades_by_regime`'s own TRENDING bucket, because
  `EmaCrossoverStrategy` never self-emits FLAT (every crossover is a
  direction reversal) and the gate classifies at the exact same decision
  bars attribution already does — locked in as a regression test.
  **The per-instrument performance table was withdrawn and has since
  been rerun for real** (FX-29, below) — see `docs/DECISIONS.md` for
  the confirmed, continuous-history numbers: TRENDING-conditioning
  helps GBP_USD/USD_JPY/XAU_USD, hurts EUR_USD, is roughly neutral for
  USD_CAD. Continuous (every-bar, not just at entry) regime monitoring
  during a held trade remains unbuilt — explicitly raised and deferred,
  not overlooked.
- `IncrementalSmaSeededEma`/`IncrementalAdx` (`forex_agent.domain.
  incremental_ema`/`incremental_adx`, FX-29): O(1)-per-update
  counterparts to every strategy's own from-scratch `_sma_seeded_ema`/
  `classify_regime` recompute, proven bit-for-bit identical to them
  (checked step-by-step, not just at the end; stress-tested against
  1,500 real H1 candles with 0 mismatches). `IncrementalStrategy` +
  `run_backtest_incremental` (`forex_agent.domain.incremental_strategy`)
  — same guarantees as `Strategy`/`run_backtest`, one O(n) forward pass,
  no reslicing. `IncrementalEmaCrossoverStrategy`/
  `IncrementalEmaCrossoverTrendRegimeGatedStrategy` — same
  `strategy_key`s as their slow counterparts (same strategy, faster
  implementation), golden-parity-tested trade-for-trade against them.
  Existing `Strategy`/`run_backtest`/`simulate_trades` and all 8
  existing strategies are completely unmodified — this is additive
  infrastructure, not a replacement, and the slow path remains the
  permanent correctness reference. Measured: a full 62,194-candle H1
  series in 0.19s (EMA) / 0.47s (gated) — down from an extrapolated
  35-40 minutes each with the old O(n²) engine. Used to rerun FX-28's
  withdrawn comparison continuously (no chunking); the corrected table
  is in `docs/DECISIONS.md`. `IncrementalStrategy` gained `reset()`
  (FX-29H, external review) — `run_backtest_incremental` calls it
  truly unconditionally, the very first thing it does (a second review
  round caught that the first version of this fix still skipped
  `reset()` for an empty `candles` list, despite the docstring already
  claiming "unconditionally" — fixed by moving the call, not softening
  the claim), since a stateful strategy instance reused across calls
  without it silently produced different results the second time
  (reproduced directly before fixing). `candles` is validated in full
  (including finalized status) before `on_candle` is ever called, so a
  rejected series can't leave a strategy partially mutated either.
- Ingestion watermark hardening (FX-30/FX-31/FX-31H, prompted by the
  same external review, explicitly noted as not affecting already-
  loaded research data): `BackfillCandles` now floors both
  `earliest_ingested` and `latest_ingested` to genuine candle
  boundaries via `candle_boundary.candle_start_boundary` (never rounds
  up — a mid-candle `end` may still be forming, so rounding up could
  falsely claim an unformed candle as covered) — closes the root cause
  behind FX-27H.1's `DetectDataGaps` symptom. Concurrent-backfill
  protection is a dedicated `BackfillLock` port (`application/ports/
  backfill_lock.py`), not a method on `IngestionWatermarkRepository` —
  FX-31's first attempt put an advisory lock there, issued through the
  same `AsyncSession` used for `candles`/`watermarks` work, which
  turned out unsafe: `Session.commit()` checks its connection back into
  the pool, and a Postgres advisory lock belongs to the physical
  connection, not the session — confirmed directly (pool checkin/
  checkout event tracing, then a real reproduced failure under forced
  contention) before fixing. `PostgresBackfillLock` now pins one
  dedicated `AsyncConnection` for the lock's entire held duration,
  structurally immune to the session's own connection churn — verified
  under a deliberately constrained, heavily-churning pool that the lock
  itself is kept isolated from. A further, distinct risk from sharing
  one connection pool between the lock and the worker sessions — a
  pool-starvation deadlock (`pg_advisory_lock` blocks while holding a
  connection; under a small shared pool, a waiting caller's held
  connection can starve the lock-holder's own worker session of the
  connection it needs to finish and release the lock) — was caught by
  external review and confirmed directly in the actual composition
  root, which shared one engine for both. Fixed with a new, dedicated
  `get_lock_engine()` (`infrastructure/db/session.py`), never shared
  with the engine backing `candles`/`watermarks` sessions; every
  `PostgresBackfillLock` construction in the codebase now uses it.
- `AlwaysLongStrategy`, `AlwaysShortStrategy`, `PreviousBarDirectionStrategy`,
  `NoTradeStrategy` (`forex_agent.domain.strategies.control`,
  `strategy_key`s `always_long_v1`/`always_short_v1`/
  `previous_bar_direction_v1`/`no_trade_v1`, FX-22) — control strategies,
  not trading ideas: a no-skill scoreboard every real strategy's
  `compute_metrics` output gets compared against on the same sample.
  Grouped in one file, a deliberate departure from every other
  strategy's one-file-per-strategy convention, since these are a
  matched baseline set. Always-long/always-short combine with FX-11's
  same-direction-no-op rule to become genuine buy-and-hold/sell-and-hold
  baselines (verified: firing every bar still produces exactly one
  trade). `PreviousBarDirectionStrategy` has no lookback or threshold
  (deliberately simpler than FX-16's momentum strategy). `NoTradeStrategy`
  always returns `None` — `compute_metrics` can't even be called on zero
  trades, which is the point. Run across the full 10-year, 5-instrument
  research dataset (FX-32) — `AlwaysLong`/`AlwaysShort` behaved exactly
  as designed; `PreviousBarDirectionStrategy` produced this project's
  first genuinely decisive result: unprofitable on every instrument,
  profit factor 0.58-0.78, at n=30,000+ trades each — see
  `docs/DECISIONS.md` for the full table.
- `BacktestMetrics` + `compute_metrics` (`forex_agent.domain.
  backtest_metrics`, FX-17): trade/win/loss/breakeven counts, win rate,
  average win/loss, expectancy, profit factor, total P&L, max drawdown,
  Sharpe/Sortino. Sharpe/Sortino are explicitly *not* annualized
  percentage-return ratios — computed on raw per-trade `Money` P&L (no
  position sizing exists yet), useful only for relative comparison
  between strategies on the same instrument/timeframe. Deliberately
  composable: no grouping/segmentation built in — "long vs short" etc. is
  filtering the trade list before calling `compute_metrics`, not a
  feature of the function itself. Requires all trades share one
  `instrument`, not merely one P&L currency (FX-21H.1) — `Instrument`
  equality already implies currency equality, so this is strictly
  stronger and catches e.g. `EUR_USD` + `GBP_USD` (both USD-quoted, but
  not comparable per-unit-notional). Verified against an independent
  reference calculation for every field.
- `run_backtest` (`forex_agent.domain.backtest`): walks candles to a
  `Strategy` one bar at a time (`candles[0:i+1]`, never further) and
  collects the `TradeHypothesis` values produced — the actual look-ahead
  prevention CLAUDE.md requires. Validates one instrument, one
  granularity, strictly ascending timestamps, that every returned
  hypothesis is timestamped at the current bar, that every returned
  hypothesis is for the same instrument as the candles being replayed
  (FX-11H), and that every returned hypothesis's `timeframe` matches the
  candles' granularity (FX-21H.1) — `TradeHypothesis.timeframe` (FX-13)
  is now structurally enforced, not advisory. `O(n²)` reslicing, known
  and accepted for now.
- `SimulatedTrade` + `simulate_trades` (`forex_agent.domain.
  trade_simulation`): turns a backtest's hypotheses into simulated
  round-trip trades. **Next-bar execution (FX-11H)**: a hypothesis
  generated from bar N executes at bar N+1's open — never bar N's own
  close, which is unrealistic (that price is only known once the bar has
  already closed). Exit rule: close-and-reverse on an opposite-direction
  hypothesis (also executed at the next bar's open); same-direction
  repeat is a no-op; a hypothesis generated on the final candle in the
  dataset cannot execute at all (no next bar exists) and is silently
  not actionable; anything still open when the hypothesis list ends is
  force-closed using the *last* candle's close (there is no bar beyond
  the dataset to get a next-bar open from). `pnl` is a raw price delta
  per unit of base-currency notional — no position sizing yet.
  `simulate_trades` also now validates its inputs defensively (FX-11H):
  rejects mixed instrument/granularity, non-ascending or duplicate
  timestamps, non-finalized candles, out-of-order/duplicate hypothesis
  timestamps, hypothesis/candle instrument mismatches, and a hypothesis
  timestamp with no matching candle — rather than assuming it's only
  ever called with `run_backtest`'s own well-formed output. Also rejects
  a non-empty `hypotheses` list with empty `candles` (FX-11H.1) rather
  than silently returning `[]`. **FLAT (FX-18):** a third
  `target_position`, distinct from the LONG/SHORT close-and-reverse
  behavior above — a no-op with no open position; with one open, closes
  it at the same next-bar-open execution price and does *not* reopen. A
  later LONG/SHORT hypothesis after a FLAT close opens fresh, exactly as
  it would from a flat start.
- `candle_series.require_consistent_series` (`forex_agent.domain.
  candle_series`): the "one instrument, one granularity, strictly
  ascending `start_time`" validation, extracted (FX-12) from being
  duplicated across `run_backtest`/`simulate_trades`/`classify_regime`
  into one shared helper.
- `TrendRegime` (`TRENDING`/`RANGING`) + `classify_regime`
  (`forex_agent.domain.regime_detection`): trend-vs-range classification
  via Wilder's ADX on a synthetic midpoint approximation — bid/ask OHLC
  averaged, *not* a true provider mid price, since bid's and ask's
  period-high/low can occur at different instants (FX-12H; a true mid
  OHLC, e.g. OANDA's `price=M`, is deferred — see `docs/DECISIONS.md`).
  Deterministic technical analysis, no ML. Requires ≥ `2 × period`
  candles (default period 14, threshold 25 — Wilder's own convention,
  both configurable; `period ≥ 1` and `threshold` in [0, 100] validated).
  Cross-checked against an independently written reference
  implementation of the same algorithm, not just qualitative
  trending/ranging behavior. This closes out CLAUDE.md's current M0–M4
  phase (items 1–11).

## What does not exist yet

- Any strategy beyond the six now built (`EmaCrossoverStrategy`,
  `CloseChannelBreakoutStrategy`, `TimeSeriesMomentumStrategy`,
  `MeanReversionStrategy`, `VolatilityExpansionBreakoutStrategy`,
  `MultiTimeframeTrendStrategy`) — the original strategy-suite roadmap
  is complete as of FX-25; anything further is a new roadmap, not
  planned yet.
- Continuous regime monitoring during a held trade — `EmaCrossoverTrend
  RegimeGatedStrategy` (FX-28, below) checks the regime only at entry
  decision bars, matching `segment_trades_by_regime`'s own convention.
  Whether checking every bar and force-exiting mid-trade on a regime
  deterioration behaves differently was explicitly raised and deferred
  (user chose to accept FX-28's proven entry-gating-equals-attribution
  finding and close the story rather than build this) — a distinct,
  unbuilt experiment if picked up later.
- Position sizing / account-currency P&L — `simulate_trades`' `pnl` is
  per-unit only; multiplying by real position size is Risk Engine
  territory, not decided yet.
- Order placement of any kind — `BrokerPort` is read-only by design; see
  `docs/DECISIONS.md` (FX-3).
- A scheduled or API-triggered version of `IngestCandles`/
  `AggregateCandles`/`BackfillCandles` — `scripts/build_research_dataset.py`
  (below) is a one-off operational script, not a recurring job; nothing
  yet re-runs backfill on a schedule to keep the dataset current going
  forward.
- Incremental (O(1)-per-bar) versions of the other 8 existing
  strategies — FX-29 built the incremental engine and converted only
  the two `EmaCrossover*` strategies FX-28's rerun needed; the slow
  `Strategy`/`run_backtest` path remains the only option for everything
  else, which is fine at ~1,500-candle sample sizes but would hit the
  same O(n²) wall any of them tried at full research-dataset scale.
- Continuous (every-bar) regime monitoring during a held trade — FX-28
  and FX-29's gating strategy only checks the regime at entry decision
  bars; a variant that force-exits mid-trade on a regime deterioration
  is a distinct, unbuilt experiment, explicitly raised and deferred by
  user choice.
- A scheduled/automatic recurring backfill service — FX-31's
  concurrency protection makes this safe to build later, but nothing
  currently triggers `BackfillCandles` other than the one-off
  `scripts/build_research_dataset.py` run.
- Any CPI/GDP/employment or other non-policy-rate fundamental data,
  economic calendar, carry or rate-differential strategy, fundamental
  score, or fundamentals-driven decision logic. FX-43 (above) DOES now
  ingest real policy-rate history for USD/EUR/GBP/CAD into real
  `MacroObservationVintage` rows via real provider APIs — this is no
  longer an empty domain model, and every mapping FX-43 touched is now
  `verified=True`. What still does NOT exist: JPY policy-rate data (no
  provider mapping established, per FX-42H.1); CAD data before
  2009-04-21 (no source found, explicitly documented, not backfilled);
  ANY mapping classified `PointInTimeSafety.POINT_IN_TIME_SAFE` —
  `released_at` is an effective-date proxy, not a verified announcement
  timestamp, and `require_research_usable_mapping` still rejects every
  mapping in the registry; any data beyond policy rates (CPI, GDP,
  employment, an economic calendar); any rate differential, carry
  strategy, fundamental score, or fundamentals-driven decision logic —
  this story's own explicit instruction was to never call this data
  "carry," and it never is anywhere in this codebase.

## Next

See [NEXT_STEPS.md](NEXT_STEPS.md).
