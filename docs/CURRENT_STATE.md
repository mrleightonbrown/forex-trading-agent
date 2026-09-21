# Current State

_Last updated: 2026-09-21 (FX-39)_

## What exists

- Repository scaffolding: `apps/application/domain/infrastructure` package
  layout under `src/forex_agent/`, `tests/{unit,integration,contract,replay,golden_data}`,
  `docs/{adr,strategy-specifications,runbooks}`.
- Toolchain: Python 3.12 via `uv`, `pyproject.toml` with Ruff + mypy + pytest
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
  distinguishable from noise** — raw one-sided p-values 0.13-0.19,
  Holm-adjusted p=0.53 for all four, nowhere near significance. One
  nuance: XAU_USD/`MultiTimeframeTrendStrategy`'s regime-block CI
  barely excludes zero, but that is the secondary robustness check
  (only 6 blocks), not read as overriding the primary result. The two
  negative controls also failed to reach significance in the negative
  direction — not a method failure (verified separately on synthetic
  data) but a structural finding: every holdout sample in this
  research program, positive or negative, is too small/noisy to clear
  a rigorous bar once trade dependence is honestly modeled. FX-38/
  FX-38H's own findings (no sign flips, directional consistency) stand
  unchanged — FX-39 recalibrates confidence, it doesn't overturn them.
  Per this story's own locked, unconditional prohibition: no parameter,
  strategy, instrument, or period was changed in response to this
  result. Full tables in `docs/DECISIONS.md`'s FX-39 entries.
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

## Next

See [NEXT_STEPS.md](NEXT_STEPS.md).
